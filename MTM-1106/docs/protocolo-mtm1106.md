# Protocolo TOMATE MTM-1106 (em andamento)

## Identificação USB
- VID:PID `08f2:6811`, bcdDevice 20.24
- Fabricante: `SZ PENG YI LTD.`; produto: `[T501] Driver Inside Tablet`; serial: `Internal CDROM! 001`
- Interfaces:
  | Iface | Classe | Função |
  |---|---|---|
  | 0 | Mass Storage (SCSI, 06/50) | CD virtual `TOMATE PEN DRIVER` com os drivers para Windows e macOS |
  | 1 | HID | Modo completo (vendor) |
  | 2 | HID | Modo padrão (compatível, sem driver) |

## Descritores HID (cópias em `re/inputs/descriptors/`)
### Iface 1 (`iface1_hidraw4.bin`)
- **Report 6**: vendor page `0xFFA0`, 63 bytes de input e 63 bytes de feature. É o canal de comando do driver.
- **Report 3**: mouse com 8 botões, X/Y/roda relativos (int8).
- **Report 9**: caneta (Digitizer/Pen):
  - flags: Tip, Barrel, Eraser, 3 bits de padding, In Range, 1 bit de padding;
  - X: u16, 0–32767;
  - Y: u16, 0–32767;
  - Pressão: u16, 0–16383;
  - Tilt X e Tilt Y: int8, −127..127.

### Iface 2 (`iface2_hidraw5.bin`)
- **Report 1**: vendor `0xFFA0`, 7 bytes de input. **Report 8**: feature de 7 bytes.
- **Report 2**: teclado (modificadores e 5 teclas). Os botões expressos chegam como atalhos.
- **Report 5**: caneta:
  - flags: Tip, Barrel, Eraser, Invert, padding, In Range;
  - X: u16, 0–4096;
  - Y: u16, 0–4096;
  - Pressão: u16, 0–2047.
- **Report 4**: Consumer Control (u16, 0–572).

## Comandos do driver Windows (análise estática com REA + Ghidra 12.2)
Análise feita sobre o `TabletService.exe` do CD virtual da própria mesa. O executável, o pseudocódigo e as evidências do REA **não são publicados** (material do fabricante); os endereços `FUN_xxxxxxxx` citados permitem refazer a análise a partir do CD da sua mesa.

- O `TabletService.exe` (Delphi + JVCL `JvHidController`) carrega o `HID.dll` dinamicamente (`FUN_0046b6ec`).
- O ponteiro de `HidD_SetFeature` (`0x4c51c0`) é chamado só pelo wrapper `FUN_0046d4fc`. O buffer enviado é o campo `+0x54` do objeto da mesa, inicializado como `08 00 00 00 00 00 00 00` (`FUN_00495630`). Portanto é o **feature report 8 da iface 2** (1 byte de ID + 7 bytes).
- Formato do comando: `08 <cmd> <d1> <d2> <d3> <d4> <d5> <d6>`.

| cmd | Função | Construtor | Uso no driver |
|---|---|---|---|
| 0 / 1 / 3 | Modo de operação; os dados levam um retângulo de 12 bits (`FUN_004954f8`) | `FUN_00495cc8` | 3 ou 1 ao iniciar (conforme configuração `0x3e6`); **0 ao sair** do driver |
| 4 | 6 bytes de configuração (`+0xa8..+0xad`, padrão `1d 01 00 00 00 00`) | `FUN_00495464` | Junto com a gravação na flash pelo CD virtual (`EraseBlock`/`WriteBuffer` em `TabletCom_vc.dll`) |
| 6 | Opções: d1 = flag, d2 = valor, d3 = 1 se a área for diferente de 0..0xFFF | `FUN_00494d80` | Configurações do usuário |
| 7 | **Área ativa em hardware**: left/top em 12 bits, depois largura/altura em 12 bits | `FUN_00494c6c` | Mapeamento da área |

- Entre um comando e outro, o driver espera pelo menos 300 ms.
- A escala padrão do driver é 0..4095 (`TSetting.ini`: `TabletMapRight=4095`).

## Observação em tempo real (Linux, após `08 03 00 00 00 00 00 00`)
Captura: `re/captures/listen_mode3b.txt` (60 s, 5.458 reports).
- **Caneta**: report 5 da iface 2 (hidraw5), 8 bytes: `05 FF XX XX YY YY PP PP` (little-endian).
  - FF = flags: bit0 ponta; bit6 em alcance (0xC0 flutuando, 0xC1 tocando); bit1 e bit2 deveriam ser os botões laterais pelo descritor (ainda não vistos).
  - X: 0–4095; Y: 0–4095 (observado de 169 a 4079).
  - Pressão: 0–2047 pelo descritor (máximo observado: 1135).
- **Botões expressos**: report 2 da iface 2 (teclado) já com atalhos fixos: `b`, `e`, `Ctrl` + `+`, `Ctrl` + `-`, `[`, `]`, `Tab`, `Espaço`, `Ctrl`, `Alt`, `Ctrl+Z`, `Ctrl+Shift+Z`.
- **Iface 1**: só apareceu o report 3 (mouse) com roda ±1. **O report 9 (alta resolução) não apareceu.**

## Conclusão atual
- A resolução real usada pelo driver oficial é **4096×4096 com 2048 níveis de pressão**, via report 5. O descritor da iface 1 (32767 / 16383 / tilt) parece ser só um descritor de compatibilidade; nem o código do driver nem a mesa o usam no modo 3.
- O app vai ler o report 5 e o report 2 da hidraw5, fazer grab dos `event*` do kernel e reemitir pelo uinput.
- Ainda em aberto: os botões da caneta (bits 1/2 do report 5 ou a roda do report 3 da iface 1?).

## Correção (2026-11-18): o que cada modo faz de fato
| Estado | Caneta sai em | Formato |
|---|---|---|
| Ao ligar (sem comando) | iface 2, report 5 | `05 FF XX XX YY YY PP PP` LE, 0–4095, pressão 0–2047 |
| `08 00` | iface 1, report 9 | `09 FF XX XX YY YY PP PP TX TY` LE, 0–32767, pressão 0–16383, tilt int8 |
| `08 03` | iface 1, report 6 (63 bytes) | fluxo bruto: `06 XX XX YY YY …` **big-endian**, ~156 Hz enquanto há caneta. O kernel não decodifica (`hid_field_extract() n (63) > 32`) |

A conclusão anterior ("modo 3 → report 5") estava errada: na captura de ontem a mesa provavelmente ainda estava no estado de fábrica. O daemon usa `08 00`.

Outros reports vistos na iface 2:
- Report 4 (Consumer Control, `04 LO HI`): ícones impressos na mesa. Usages E2, EA, E9, 183, CD, B6, B5, 223, 192.
- Report 2 com `08 00 07` (`Super+D`).
- Report 1 `01 80 00 …` esporádico (significado desconhecido).
