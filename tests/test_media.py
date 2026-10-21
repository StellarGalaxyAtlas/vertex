import os
import threading

import pytest

from vertex.media import (
    export,
    mixing,
    probe,
    thumbnails,
    track_volume,
    tracks,
    trim,
    waveform,
)
from vertex.media.ffmpeg import Cancelled, MediaError
from vertex.media.probe import AudioTrack


def _tracks(*names):
    return [AudioTrack(index=i, name=name) for i, name in enumerate(names)]


class TestProbeParsing:
    def test_parse(self):
        info = probe.parse_probe({
            "format": {"duration": "10.0", "size": "1250000"},
            "streams": [
                {"codec_type": "video", "width": 1920, "height": 1080,
                 "avg_frame_rate": "60/1", "r_frame_rate": "60/1"},
                {"codec_type": "audio", "tags": {"title": "Vertex Game"}},
                {"codec_type": "audio", "tags": {"handler_name": "SoundHandler"}},
                {"codec_type": "audio", "tags": {"handler_name": "Mic"}},
            ],
        })
        assert (info.width, info.height, info.fps, info.duration) == (1920, 1080, 60.0, 10.0)
        assert info.bitrate == 1_000_000      # derived from size when bit_rate is absent
        assert [(t.index, t.name, t.has_name) for t in info.tracks] == [
            (0, "Vertex Game", True), (1, "Audio 2", False), (2, "Mic", True)]
        assert info.summary == "1080p60"

    def test_name_tag_wins_for_saved_volume_compatibility(self):
        assert probe.track_name({"name": "a", "title": "b"}, 1) == ("a", True)


class TestMixing:
    def test_mpv_graph_holds_no_gains(self):
        a, b = _tracks("a", "b")
        fmt = "aformat=sample_rates=48000:channel_layouts=stereo"
        assert mixing.mpv_graph([a, b]) == (
            f"[aid1]{fmt}[s0];[aid2]{fmt}[s1];[s0][s1]amerge=inputs=2[ao]")
        b.volume = 0.3
        assert mixing.mpv_graph([a, b]) == mixing.mpv_graph(_tracks("a", "b"))
        assert mixing.mpv_graph([a]) == f"[aid1]{fmt}[ao]"
        assert mixing.mpv_graph([]) is None

    def test_mpv_mix_filter_keeps_muted_tracks_at_zero(self):
        a, b = _tracks("a", "b")
        b.muted = True
        assert mixing.mpv_mix_filter([a, b]) == (
            "@mix:lavfi=[asplit=2[i0][i1];"
            "[i0]pan=stereo|c0=c0|c1=c1,volume@v0=1.0[t0];"
            "[i1]pan=stereo|c0=c2|c1=c3,volume@v1=0.0[t1];"
            "[t0][t1]amix=inputs=2:normalize=0]")
        assert mixing.mpv_mix_filter([]) is None

    def test_ffmpeg_graph_drops_inaudible_tracks(self):
        a, b, c = _tracks("a", "b", "c")
        b.volume = 0
        c.volume = 0.5
        assert mixing.ffmpeg_graph([a, b, c]) == (
            "[0:a:0]volume=1.0[m0];[0:a:2]volume=0.5[m1];[m0][m1]amix=inputs=2:normalize=0[ao]")
        a.muted = c.muted = True
        assert mixing.ffmpeg_graph([a, b, c]) is None


class TestTrackLabels:
    def test_vertex_tracks_are_recognised_exactly(self):
        labelled = tracks.label_tracks(_tracks(
            "Vertex Mic", "Devices: Monitor of Vertex Game", "device:vertex_chat.monitor",
            "Vertex Media"))
        assert [(t.label, t.channel) for t in labelled] == [
            ("Game", "game"), ("Chat", "chat"), ("Media", "media"), ("Mic", "mic")]

    def test_a_media_track_is_its_own_lane(self):
        labelled = tracks.label_tracks(_tracks("Vertex Game", "Vertex Mic", "Vertex Media"))
        assert [t.label for t in labelled] == ["Game", "Media", "Mic"]
        assert tracks.guess_source("Spotify music") == "media"

    def test_aux_tracks_are_numbered_not_called_the_mic(self):
        labelled = tracks.label_tracks(_tracks("Vertex Game", "Devices: Monitor of Vertex Aux"))
        assert [(t.label, t.channel) for t in labelled] == [("Audio 1", ""), ("Audio 2", "")]

    def test_merged_outputs_are_desktop(self):
        labelled = tracks.label_tracks(_tracks(
            "Devices: Monitor of Vertex Game, Monitor of Vertex Chat", "Vertex Mic"))
        assert [t.label for t in labelled] == ["Desktop", "Mic"]

    def test_merged_with_mic_is_unlabelled(self):
        labelled = tracks.label_tracks(_tracks("device:a.monitor|device:my_mic", "Vertex Game"))
        assert [t.label for t in labelled] == ["Audio 1", "Audio 2"]

    def test_devices_named_by_what_they_carry(self):
        labelled = tracks.label_tracks(_tracks(
            "device:alsa_input.usb-Blue_Yeti", "device:Virtual_Game_Sink.monitor"))
        assert [t.label for t in labelled] == ["Game", "Mic"]

    def test_moments_handlers(self):
        labelled = tracks.label_tracks(_tracks("Mic", "Game", "Chat"))
        assert [t.label for t in labelled] == ["Game", "Chat", "Mic"]

    def test_duplicates_fall_back_to_numbers(self):
        labelled = tracks.label_tracks(_tracks("Game A", "Game B"))
        assert [t.label for t in labelled] == ["Audio 1", "Audio 2"]
        assert all(t.channel == "" for t in labelled)

    def test_placeholders_are_unlabelled(self):
        info = probe.parse_probe({"streams": [{"codec_type": "audio"}]})
        assert tracks.label_tracks(info.tracks)[0].label == "Audio 1"


class TestExportPlan:
    def test_fits_budget_and_steps_down(self):
        plan = export.plan(60, 2560, 1440, 60, True, 25 * export.MB)
        assert plan.estimate(60) <= 25 * export.MB
        assert plan.height < 1440
        assert plan.width % 2 == 0

    def test_short_clip_is_capped_by_quality_ceiling(self):
        plan = export.plan(5, 1920, 1080, 60, True, 100 * export.MB)
        assert plan.height == 1080
        assert plan.estimate(5) < 50 * export.MB

    def test_too_long(self):
        with pytest.raises(MediaError):
            export.plan(3600, 1920, 1080, 60, True, 10 * export.MB)

    def test_copy_estimate(self):
        info = probe.MediaInfo(bitrate=8_000_000)
        assert export.copy_estimate(info, 10) == 10_000_000
        assert export.copy_estimate(probe.MediaInfo(), 10) == 0

    def test_export_target_names(self, tmp_path):
        first = export.export_target(str(tmp_path), "clip.mp4", 25 * export.MB)
        assert os.path.basename(first) == "clip (25MB).mp4"
        open(first, "w").close()
        assert os.path.basename(export.export_target(str(tmp_path), "clip.mp4", 25 * export.MB)) \
            == "clip (25MB) 2.mp4"
        assert os.path.basename(export.export_target(str(tmp_path), "clip.mkv", None)) == \
            "clip (Original).mp4"


@pytest.mark.ffmpeg
class TestWithFfmpeg:
    def test_probe_and_label(self, sample_clip):
        info = probe.probe(sample_clip)
        assert (info.width, info.height) == (320, 180)
        assert abs(info.duration - 4) < 0.2
        labelled = tracks.label_tracks(info.tracks)
        assert [t.label for t in labelled] == ["Game", "Chat", "Mic"]

    def test_waveform(self, sample_clip):
        levels = waveform.peaks(sample_clip, 0, 4.0, buckets=50)
        assert 45 <= len(levels) <= 51
        assert max(levels) > 0.1          # lavfi's sine peaks at 1/8 full scale
        silent = waveform.peaks(sample_clip, 2, 4.0, buckets=50)
        assert max(silent) < 0.01
        assert waveform.peaks(sample_clip, 9, 4.0) == []
        cancel = threading.Event()
        cancel.set()
        assert waveform.peaks(sample_clip, 0, 4.0, cancel=cancel) == []

    def test_trim_keeps_every_track_and_its_title(self, sample_clip, tmp_path):
        out = str(tmp_path / "trimmed.mp4")
        size = trim.trim(sample_clip, out, 1.0, 3.0)
        assert size > 0
        info = probe.probe(out)
        assert [t.name for t in info.tracks] == [
            "Vertex Game", "Devices: Monitor of Vertex Chat", "Vertex Mic"]
        assert info.duration <= 3.2
        assert trim.keyframe_before(sample_clip, 2.5) <= 2.5

    def test_track_volume_is_set_in_the_clip_and_the_rest_copied(self, sample_clip, tmp_path):
        import shutil
        import subprocess

        def loudness(path, position):
            out = subprocess.run(["ffmpeg", "-hide_banner", "-i", path, "-map", f"0:a:{position}",
                                  "-af", "volumedetect", "-f", "null", "-"],
                                 capture_output=True, text=True, check=True).stderr
            return float(out.split("mean_volume:")[1].split("dB")[0])

        folder = tmp_path / "clips"
        folder.mkdir()
        clip = str(folder / "clip.mp4")
        shutil.copy2(sample_clip, clip)
        before = (os.path.getmtime(clip), loudness(clip, 0), loudness(clip, 1))
        assert not track_volume.apply(clip, {0: 100, 1: 100})       # nothing to do
        assert track_volume.apply(clip, {0: 50, 1: 100, 7: 30})
        assert os.listdir(folder) == ["clip.mp4"]                   # no staging file left
        assert os.path.getmtime(clip) == before[0]
        assert loudness(clip, 0) == pytest.approx(before[1] - 6.0, abs=0.5)
        assert loudness(clip, 1) == pytest.approx(before[2], abs=0.1)
        info = probe.probe(clip)
        assert [t.name for t in info.tracks] == [
            "Vertex Game", "Devices: Monitor of Vertex Chat", "Vertex Mic"]
        assert info.duration == pytest.approx(probe.probe(sample_clip).duration, abs=0.1)

    def test_track_volume_reencodes_only_the_tracks_it_changes(self):
        argv = track_volume.command("in.mp4", "out.mp4", {1: 150},
                                    [{"codec_name": "aac", "bit_rate": "128000"},
                                     {"codec_name": "opus", "bit_rate": "96000"}], {})
        assert argv[argv.index("-c") + 1] == "copy"
        assert argv[argv.index("-filter:a:1") + 1] == "volume=1.5"
        assert argv[argv.index("-c:a:1") + 1] == "libopus"
        assert argv[argv.index("-b:a:1") + 1] == "96000"
        assert "-filter:a:0" not in argv and "-c:a:0" not in argv
        assert track_volume.changes([100, 80, 100, 120]) == {1: 80, 3: 120}

    def test_trim_rejects_empty_selection(self, sample_clip, tmp_path):
        with pytest.raises(MediaError):
            trim.trim(sample_clip, str(tmp_path / "x.mp4"), 1.0, 1.01)

    def test_export_original_and_capped(self, sample_clip, tmp_path):
        info = probe.probe(sample_clip)
        mix = tracks.label_tracks(info.tracks)
        mix[2].muted = True
        progress = []
        folder = tmp_path / "exports"
        result = export.export_clip(sample_clip, "clip.mp4", str(folder), 0.5, 3.5, mix, info,
                                    None, progress.append)
        assert os.path.exists(result.path) and progress
        out = probe.probe(result.path)
        assert len(out.tracks) == 1             # one mixed stereo track

        result = export.export_clip(sample_clip, "clip.mp4", str(folder), 0.0, 4.0, mix, info,
                                    10 * export.MB)
        assert result.size <= 10 * export.MB and not result.over_limit
        assert not [n for n in os.listdir(folder) if n.startswith(".")]

    def test_export_cancel_leaves_nothing(self, sample_clip, tmp_path):
        info = probe.probe(sample_clip)
        cancel = threading.Event()
        cancel.set()
        folder = tmp_path / "exports"
        with pytest.raises(Cancelled):
            export.export_clip(sample_clip, "clip.mp4", str(folder), 0, 4, info.tracks, info,
                               10 * export.MB, cancel=cancel)
        assert os.listdir(folder) == []

    def test_thumbnails(self, sample_clip, tmp_path):
        cache = thumbnails.ThumbnailCache(str(tmp_path))
        assert cache.cached_thumbnail(sample_clip) is None
        thumb = cache.thumbnail(sample_clip)
        assert thumb and os.path.getsize(thumb) > 0
        assert cache.cached_thumbnail(sample_clip) == thumb
        frames = cache.preview(sample_clip)
        assert len(frames) >= 10
        assert cache.prune([]) >= 2
        assert cache.cached_thumbnail(sample_clip) is None

    def test_thumbnails_are_made_again_at_another_size(self, sample_clip, tmp_path,
                                                         monkeypatch):
        from PySide6.QtGui import QImage

        cache = thumbnails.ThumbnailCache(str(tmp_path))
        thumb = cache.thumbnail(sample_clip)
        assert QImage(thumb).width() == thumbnails.THUMB_WIDTH
        monkeypatch.setattr(thumbnails, "THUMB_WIDTH", 640)
        assert cache.cached_thumbnail(sample_clip) is None     # another size: made again
        assert QImage(cache.thumbnail(sample_clip)).width() == 640
        assert cache.prune([sample_clip]) == 1                 # the old one goes
