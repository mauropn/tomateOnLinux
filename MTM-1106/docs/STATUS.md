# Status do projeto (atualizado em 2026-11-18)

## Feito
- **Engenharia reversa** (REA 6.9.0 + Ghidra 12.2 sobre o `TabletService.exe` do CD virtual da mesa). Detalhes em `docs/protocolo-mtm1106.md`.
  - Comando de modo: feature report 8 na iface 2, `08 03 00 00 00 00 00 00`.
  - Caneta: report 5, X/Y 0–4095, pressão 0–2047. Os 12 botões chegam como atalhos de teclado (report 2) e como roda (report 3 da iface 1).
- **App Python** em `tomate/`:
  - daemon com uinput e grab;
  - GUI PySide6 com 5 abas;
  - 29 testes passando.
- **Instalado**:
  - `scripts/setup-system.sh` (pacotes e udev) rodado com sudo;
  - `scripts/install-user.sh` rodado: serviço `tomate-daemon` ativo no login e atalho "Mesa TOMATE" no menu.
- **Verificado na máquina**:
  - o daemon abre a mesa, cria os dispositivos virtuais e detecta os 2 monitores via Mutter;
  - a GUI conecta ao daemon;
  - ao sair, o daemon limpa os dispositivos e o socket.

## 2026-11-18: correção do modo
- **Bug**: o daemon mandava `08 03` (modo 3). Isso joga a mesa num fluxo bruto (report 6 da iface 1, só o driver Windows decodifica). A caneta parava, inclusive para o kernel. Trocar de porta USB "consertava" só porque reiniciava a mesa.
- **Modos observados**:
  - ao ligar: report 5 na iface 2 (12 bits, pressão 2047);
  - `08 00`: **report 9 na iface 1**: X/Y 0–32767, pressão 0–16383 e inclinação int8. O kernel também entende esse report. Isso resolve o "modo 0 ambíguo";
  - `08 03`: report 6 bruto (`06 XX XX YY YY …`, big-endian). Não usar.
- **Daemon agora**:
  - envia `08 00`;
  - aceita os reports 5 e 9 numa escala interna 32767/16383;
  - o dispositivo virtual expõe inclinação (`ABS_TILT_X/Y`);
  - repassa as teclas multimídia (report 4, ícones impressos na mesa) e atalhos desconhecidos como `Super+D`.
- **Testado pelo usuário**: o cursor segue a caneta e a área cobre os 2 monitores; os 12 botões são reconhecidos.

## 2026-11-22: cursor preso à esquerda até a metade da mesa
- **Sintoma**: na metade esquerda da mesa o X saía sempre 0; na metade direita ia de 0 a 32767 (o cursor "corria" até o 2º monitor). Já acontecia no report 5 (captura `listen_mode3b.txt`: 2400 de 5430 amostras com X=0). O Y estava ok.
- **Causa**: área ativa em hardware gravada na mesa começando no meio do X (provavelmente deixada pelo driver Windows).
- **Correção**: `Tablet.init_mode` manda, depois do modo, o comando 7 (`FUN_00494c6c`) com a mesa inteira: `08 07 00 00 00 ff ff ff` (`protocol.area_command`). O comando de modo também passou a levar o retângulo `ScreenMap` padrão (0, 0, 4095, 4095), como o driver: `08 00 00 ff f0 00 ff f0`. Confirmado pelo usuário.
- Testado também após trocar de porta USB (3-2.2 → 3-4): o daemon reconectou sozinho e o X cobriu a mesa inteira (0–32521, valores em todas as faixas).

## Próximos passos
1. **Testar com uso real**:
   - [x] O cursor segue a caneta (com o alvo "todos").
   - [ ] Mapeamento com o alvo "LG" ou "eDP".
   - [ ] Pressão e inclinação no Krita/GIMP.
   - [x] Ícones multimídia impressos na mesa (volume, play): funcionando.
   - [x] Cursor fantasma parado: era o nó do kernel da mesa preso em "caneta próxima" quando o daemon o capturava. Corrigido: antes do grab e depois do ungrab, o daemon lê o estado com EVIOCGKEY e injeta a liberação (`kernel.evdev_release_keys`). Leitura do estado validada; o fantasma não voltou.
   - [ ] Ação "Alternar monitor", HDMI, suspender e retomar.
2. **Rótulos dos botões na GUI**: a ordem física é B1, B2, B3, B4, **B6, B5**, roda↑ (B11), B7, B8, roda↓ (B12), B9, B10. Os IDs vêm do atalho de fábrica, não da posição.
3. **Botões laterais da caneta**: nenhum sinal nem no modo 0 (report 9, bits 1/2). Ainda falta tentar o modo 1 e capturar no Windows.

## Comandos úteis
```bash
systemctl --user status tomate-daemon            # estado do serviço
journalctl --user -u tomate-daemon -f            # log ao vivo
systemctl --user stop tomate-daemon              # parar (necessário para usar hidprobe com exclusividade / rodar em 1º plano)
.venv/bin/python -m tomate.daemon -v             # daemon em primeiro plano
python3 re/tools/hidprobe.py listen 20           # reports brutos da mesa
python3 re/tools/hidprobe.py setfeature 5 0803000000000000
.venv/bin/python -m pytest
systemctl --user disable --now tomate-daemon     # desligar o driver (mesa volta ao original)
```

## Ambiente
- Ubuntu 26.04, GNOME Wayland. Monitores: eDP-1 1920×1200 em (0,0) e HDMI-1 LG UltraWide 2560×1080 em (1920,0).
- REA: `rea` global (nvm, Node 22.23.5), registrado no Claude Code via `rea setup`. As ferramentas MCP aparecem depois de reiniciar o Claude Code.
- Ghidra: `~/.local/opt/ghidra_12.2_PUBLIC` com `JAVA_HOME=/usr/lib/jvm/java-25-openjdk-amd64`.
- `sudo` não funciona pelo `!` do Claude Code: rode-o num terminal à parte.
