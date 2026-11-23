import pytest

from tomate.mapping import (TABLET_ASPECT, VIRTUAL_MAX, Mapper, MappingSettings, Monitor,
                            PressureCurve, Rect, bounding_box, effective_tablet_area)
from tomate.monitors import parse_mutter_state, parse_xrandr

# Layout real da máquina: notebook 1920x1200 + LG ultrawide 2560x1080 à direita
EDP = Monitor("CSW|MNG007QX2-2|0x00000000", "eDP-1", "Built-in display",
              Rect(0, 0, 1920, 1200), True)
HDMI = Monitor("GSM|LG ULTRAWIDE|0x01010101", "HDMI-1", 'LG Electronics 34"',
               Rect(1920, 0, 2560, 1080))
MONS = [EDP, HDMI]


def corners(m: Mapper):
    return [m.to_desktop(x, y) for x, y in ((0, 0), (32767, 0), (0, 32767), (32767, 32767))]


def test_bounding_box():
    assert bounding_box(MONS) == Rect(0, 0, 4480, 1200)


def test_all_monitors_without_aspect():
    m = Mapper(MappingSettings(target="all", keep_aspect=False), MONS)
    assert corners(m) == [(0, 0), (4480, 0), (0, 1200), (4480, 1200)]
    assert m.to_virtual(32767, 32767) == (VIRTUAL_MAX, VIRTUAL_MAX)


def test_single_monitor_corners():
    for mon in MONS:
        m = Mapper(MappingSettings(target="monitor", monitor=mon.key, keep_aspect=False), MONS)
        r = mon.rect
        assert corners(m) == [(r.x, r.y), (r.x + r.w, r.y), (r.x, r.y + r.h),
                              (r.x + r.w, r.y + r.h)]


def test_monitor_by_connector_name():
    m = Mapper(MappingSettings(target="monitor", monitor="HDMI-1"), MONS)
    assert m.output == HDMI.rect


def test_missing_monitor_falls_back_to_all():
    m = Mapper(MappingSettings(target="monitor", monitor=HDMI.key), [EDP])
    assert m.effective_target == "all"
    assert m.output == EDP.rect


def test_region():
    s = MappingSettings(target="region", region=Rect(100, 100, 800, 600), keep_aspect=False)
    m = Mapper(s, MONS)
    assert corners(m)[0] == (100, 100) and corners(m)[3] == (900, 700)


def _physical_aspect(area: Rect) -> float:
    return area.w / area.h * TABLET_ASPECT


@pytest.mark.parametrize("mon", MONS)
def test_keep_aspect_matches_output(mon):
    s = MappingSettings(target="monitor", monitor=mon.key, keep_aspect=True)
    area = effective_tablet_area(s, mon.rect)
    assert _physical_aspect(area) == pytest.approx(mon.rect.aspect, rel=1e-6)
    assert Rect(0, 0, 1, 1).contains(area)


def test_keep_aspect_ultrawide_crops_height_centered():
    s = MappingSettings(target="monitor", monitor=HDMI.key, keep_aspect=True)
    area = effective_tablet_area(s, HDMI.rect)  # 21:9 é mais largo que a mesa → corta altura
    assert area.w == 1 and area.h < 1
    assert area.y == pytest.approx((1 - area.h) / 2)


def test_keep_aspect_all_monitors():
    s = MappingSettings(target="all", keep_aspect=True)
    area = effective_tablet_area(s, bounding_box(MONS))
    assert _physical_aspect(area) == pytest.approx(4480 / 1200)


def test_rotation():
    s = MappingSettings(target="monitor", monitor=EDP.key, keep_aspect=False, rotation=180)
    m = Mapper(s, MONS)
    assert m.to_desktop(0, 0) == (1920, 1200)
    s.rotation = 90
    m = Mapper(s, MONS)
    assert m.to_desktop(0, 0) == (1920, 0)       # canto sup. esquerdo da mesa → sup. direito
    assert m.to_desktop(32767, 0) == (1920, 1200)


def test_rotation_keep_aspect_uses_inverted_aspect():
    s = MappingSettings(target="monitor", monitor=EDP.key, keep_aspect=True, rotation=90)
    area = effective_tablet_area(s, EDP.rect)
    assert _physical_aspect(area) == pytest.approx(1200 / 1920)


def test_tablet_area_clamps_outside_points():
    s = MappingSettings(target="monitor", monitor=EDP.key, keep_aspect=False,
                        tablet_area=Rect(0.25, 0.25, 0.5, 0.5))
    m = Mapper(s, MONS)
    assert m.to_desktop(0, 0) == (0, 0)
    assert m.to_desktop(32767, 32767) == (1920, 1200)


def test_pressure_linear_identity():
    c = PressureCurve()
    for raw in (0, 1, 100, 8191, 16383):
        assert abs(c.apply(raw) - raw) <= 1


def test_pressure_soft_and_firm():
    soft = PressureCurve(p1=(0.0, 0.6), p2=(0.4, 1.0))
    firm = PressureCurve(p1=(0.6, 0.0), p2=(1.0, 0.4))
    assert soft.apply(512) > 512 > firm.apply(512)


def test_pressure_threshold_and_saturation():
    c = PressureCurve(threshold=0.1, saturation=0.8)
    assert c.apply(100) == 0
    assert c.apply(int(16383 * 0.85)) == 16383
    lut = c.lut()
    assert lut == sorted(lut)  # monotônica


def test_parse_mutter_state():
    body = (
        1,
        [(("HDMI-1", "GSM", "LG ULTRAWIDE", "0x01010101"),
          [("2560x1080@60", 2560, 1080, 60.0, 1.0, [1.0], {"is-current": ("b", True)})],
          {"display-name": ("s", 'LG Electronics 34"'), "is-builtin": ("b", False)}),
         (("eDP-1", "CSW", "MNG007QX2-2", "0x00000000"),
          [("1920x1200@144", 1920, 1200, 144.0, 1.0, [1.0], {"is-current": ("b", True)})],
          {"display-name": ("s", "Built-in display"), "is-builtin": ("b", True)})],
        [(0, 0, 1.0, 0, True, [("eDP-1", "CSW", "MNG007QX2-2", "0x00000000")], {}),
         (1920, 0, 1.0, 0, False, [("HDMI-1", "GSM", "LG ULTRAWIDE", "0x01010101")], {})],
        {"layout-mode": ("u", 1)},
    )
    assert parse_mutter_state(body) == MONS


def test_parse_mutter_scaled_and_rotated():
    body = (1,
            [(("DP-1", "A", "B", "C"),
              [("3840x2160", 3840, 2160, 60.0, 2.0, [2.0], {"is-current": ("b", True)})], {})],
            [(0, 0, 2.0, 1, True, [("DP-1", "A", "B", "C")], {})],
            {"layout-mode": ("u", 1)})
    assert parse_mutter_state(body)[0].rect == Rect(0, 0, 1080, 1920)


def test_parse_xrandr():
    text = ("Monitors: 2\n 0: +*eDP-1 1920/340x1200/220+0+0  eDP-1\n"
            " 1: +HDMI-1 2560/800x1080/340+1920+0  HDMI-1\n")
    mons = parse_xrandr(text)
    assert [m.connector for m in mons] == ["eDP-1", "HDMI-1"]
    assert mons[1].rect == Rect(1920, 0, 2560, 1080) and mons[0].builtin
