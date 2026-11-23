from tomate import keys
from tomate import protocol as P


def test_parse_pen_report5_scaled():
    # capturado em re/captures/listen_mode3b.txt (estado de fábrica, 12 bits)
    s = P.parse_pen(bytes.fromhex("05c10000b100b900"))
    assert s == P.PenSample(x=0, y=round(0xB1 * 32767 / 4095), pressure=round(0xB9 * 16383 / 2047),
                            tip=True, barrel=False, barrel2=False, in_range=True)


def test_parse_pen_report5_hover_and_clamp():
    s = P.parse_pen(bytes.fromhex("05c0ff1fff0fff7f"))
    assert s.in_range and not s.tip
    assert s.x == P.RAW_X_MAX and s.y == P.RAW_Y_MAX and s.pressure == P.RAW_PRESSURE_MAX


def test_parse_pen_report9_real():
    # capturado em 2026-11-18 após o comando de modo 0 (iface 1)
    s = P.parse_pen(bytes.fromhex("09c1ec72b803f3033a2f"))
    assert s == P.PenSample(x=0x72EC, y=0x03B8, pressure=0x03F3, tip=True, barrel=False,
                            barrel2=False, in_range=True, tilt_x=0x3A, tilt_y=0x2F)
    s = P.parse_pen(bytes.fromhex("09c00162845100002cd8"))
    assert s.in_range and not s.tip and s.pressure == 0 and s.tilt_y == -40


def test_parse_pen_rejects_other_reports():
    assert P.parse_pen(bytes.fromhex("0200000800000000")) is None
    assert P.parse_pen(b"\x05\x00") is None
    assert P.parse_pen(bytes.fromhex("09c1ec72b803")) is None
    # fluxo bruto do modo 3 não é caneta
    assert P.parse_pen(bytes.fromhex("060fff001e066a0680020aff")) is None


def test_mode_command_is_standard():
    # retângulo da mesa inteira (0, 0, 4095, 4095), como o driver Windows com o TSetting.ini padrão
    assert P.mode_command() == bytes.fromhex("080000fff000fff0")


def test_keyboard_buttons_from_capture():
    cases = {
        "0200000800000000": {"B2"},
        "0200000500000000": {"B1"},
        "0201002d00000000": {"B3"},
        "0201002e00000000": {"B4"},
        "0200002f00000000": {"B5"},
        "0200003000000000": {"B6"},
        "0200002b00000000": {"B7"},
        "0200002c00000000": {"B8"},
        "0201000000000000": {"B9"},
        "0204000000000000": {"B10"},
        "0200000000000000": set(),
    }
    for hexrep, expected in cases.items():
        mod, ks = P.parse_keyboard(bytes.fromhex(hexrep))
        assert P.keyboard_to_buttons(mod, ks) == expected, hexrep


def test_unknown_combo_is_passthrough():
    mod, ks = P.parse_keyboard(bytes.fromhex("0203001d00000000"))  # Ctrl+Shift+Z
    assert P.keyboard_to_buttons(mod, ks) == set()
    assert keys.hid_report_to_keycodes(mod, ks) == [29, 42, 44]


def test_wheel():
    assert P.parse_wheel(bytes.fromhex("0300000001")) == 1
    assert P.parse_wheel(bytes.fromhex("03000000ff")) == -1
    assert P.parse_wheel(bytes.fromhex("0300000000")) == 0


def test_mode_command_matches_driver_layout():
    assert P.mode_command(P.MODE_RAW, (0, 0, 0, 0)) == bytes.fromhex("0803000000000000")
    # v24=0x123, v26=0x456, v28=0x789, v2a=0xabc
    cmd = P.mode_command(1, (0x123, 0x456, 0x789, 0xABC))
    assert cmd == bytes([0x08, 0x01, 0x56, 0x89, 0x74, 0x23, 0xBC, 0xA1])


def test_parse_shortcut():
    assert keys.parse_shortcut("Ctrl+Shift+Z") == [29, 42, 44]
    assert keys.parse_shortcut("ctrl + z") == [29, 44]
    try:
        keys.parse_shortcut("Ctrl+Nada")
    except ValueError:
        pass
    else:
        raise AssertionError


def test_consumer_keys_from_capture():
    # ícones impressos na mesa, capturados em 2026-11-18
    assert P.parse_consumer(bytes.fromhex("04e200")) == 0xE2
    assert P.parse_consumer(bytes.fromhex("048301")) == 0x183
    assert P.parse_consumer(bytes.fromhex("040000")) == 0
    assert P.parse_consumer(bytes.fromhex("0200")) is None
    for usage in (0xE2, 0xEA, 0xE9, 0x183, 0xCD, 0xB6, 0xB5, 0x223, 0x192):
        assert usage in keys.HID_CONSUMER_TO_LINUX
    assert set(keys.HID_CONSUMER_TO_LINUX.values()) <= set(keys.all_keyboard_codes())


def test_area_command_layout():
    assert P.area_command() == bytes.fromhex("08070000" "00ffffff")
    # l=0x123, t=0x456, r=0x923, b=0xA56 → w=0x800, h=0x600
    assert P.area_command(0x123, 0x456, 0x923, 0xA56) == bytes([8, 7, 0x41, 0x23, 0x56, 0x68, 0x00, 0x00])
