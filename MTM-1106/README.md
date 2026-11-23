# tomate: mesa TOMATE MTM-1106 no Linux

Driver em userspace e aplicativo de configuração para a mesa TOMATE MTM-1106 (USB `08f2:6811`, "SZ PENG YI LTD. [T501]"). O protocolo foi obtido por engenharia reversa do driver oficial para Windows, usando o [REA](https://github.com/morluto/rea) com o Ghidra. Detalhes em [`docs/protocolo-mtm1106.md`](docs/protocolo-mtm1106.md).

## Como funciona
O `tomate-daemon`:
1. abre a mesa via hidraw e envia o comando de modo que o driver oficial usa;
2. captura com exclusividade (grab) os eventos que o kernel gera para a mesa;
3. reemite tudo por dois dispositivos virtuais `uinput`, uma caneta e um teclado/mouse, já com a configuração aplicada.

A configuração cobre:
- monitor de destino, área da mesa, proporção e rotação;
- curva de pressão;
- ações dos botões.

O `tomate-gui` edita `~/.config/tomate/config.toml` e avisa o daemon pelo socket `$XDG_RUNTIME_DIR/tomate.sock`. As mudanças valem na hora.

Os monitores vêm do GNOME/Mutter (D-Bus `org.gnome.Mutter.DisplayConfig`), com `xrandr` como reserva. O daemon acompanha a conexão e desconexão de monitores. Se o monitor escolhido sumir, a mesa passa a cobrir todos os monitores até ele voltar.

## Instalação
```bash
sudo bash scripts/setup-system.sh   # uma vez: pacotes e regras udev (acesso à mesa e ao uinput)
bash scripts/install-user.sh        # venv, serviço systemd --user e atalho "Mesa TOMATE"
```

## Uso
- Abra **Mesa TOMATE** no menu de aplicativos. As abas são Monitores, Área da mesa, Pressão, Botões e Teste.
- Serviço:
  - ver o estado: `systemctl --user status tomate-daemon`
  - acompanhar o log: `journalctl --user -u tomate-daemon -f`
- Para desligar o driver e voltar ao comportamento original da mesa: `systemctl --user disable --now tomate-daemon`.

## Desenvolvimento
```bash
.venv/bin/python -m pytest              # testes (protocolo com reports reais, mapeamento, config)
.venv/bin/python -m tomate.daemon -v    # daemon em primeiro plano (pare o serviço antes)
python3 re/tools/hidprobe.py listen 20  # ver os reports brutos da mesa
```

## Estrutura
| Caminho | Conteúdo |
|---|---|
| `tomate/protocol.py` | Formato dos reports e comandos (engenharia reversa) |
| `tomate/mapping.py` | Mesa → monitores, proporção, rotação, curva de pressão (lógica pura) |
| `tomate/monitors.py` | Monitores via Mutter/xrandr |
| `tomate/daemon.py` | Laço principal, botões, IPC |
| `tomate/kernel.py` | hidraw, evdev e uinput via ioctl |
| `tomate/gui/app.py` | Interface PySide6 |
| `re/` | Descritores HID da mesa, capturas de tráfego USB e a ferramenta `hidprobe.py`. O driver do fabricante e o pseudocódigo **não** fazem parte do repositório |
