import tomllib

from tomate import config as C
from tomate.mapping import Rect


def test_roundtrip(tmp_path):
    cfg = C.Config()
    cfg.mapping.target = "monitor"
    cfg.mapping.monitor = 'GSM|LG "ULTRAWIDE"|0x01'
    cfg.mapping.rotation = 180
    cfg.mapping.tablet_area = Rect(0.1, 0.2, 0.5, 0.6)
    cfg.pressure.p1 = (0.1, 0.5)
    cfg.pressure.threshold = 0.05
    cfg.buttons["B3"] = "key:Ctrl+Shift+Z"
    cfg.buttons["B11"] = "cycle_monitor"
    path = C.save(cfg, tmp_path / "c.toml")
    tomllib.loads(path.read_text())  # TOML válido
    back = C.load(path)
    assert back.mapping.monitor == cfg.mapping.monitor
    assert back.mapping.rotation == 180
    assert back.mapping.tablet_area == Rect(0.1, 0.2, 0.5, 0.6)
    assert back.pressure.p1 == (0.1, 0.5)
    assert back.buttons["B3"] == "key:Ctrl+Shift+Z"
    assert back.buttons["B11"] == "cycle_monitor"


def test_missing_and_invalid(tmp_path):
    assert C.load(tmp_path / "nao-existe.toml").mapping.target == "all"
    bad = tmp_path / "bad.toml"
    bad.write_text("[mapping\n")
    assert C.load(bad).mapping.target == "all"
    weird = tmp_path / "weird.toml"
    weird.write_text('[mapping]\ntarget = "xyz"\nrotation = 45\n[pressure]\nthreshold = 9\n')
    c = C.load(weird)
    assert c.mapping.target == "all" and c.mapping.rotation == 0 and c.pressure.threshold == 1.0
