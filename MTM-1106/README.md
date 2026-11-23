# TOMATE MTM-1106 no Linux

Driver e aplicativo de configuração para a mesa digitalizadora **TOMATE MTM-1106** (USB `08f2:6811`, aparece no sistema como "SZ PENG YI LTD. [T501] Driver Inside Tablet").

O fabricante só oferece driver para Windows. Este projeto foi feito por engenharia reversa do protocolo USB e não usa nem distribui nenhum código do fabricante.

## O que funciona
- **Caneta** com pressão e inclinação, em alta resolução (32768 × 32768 pontos).
- **Monitores**: a área da mesa pode cobrir todos os monitores, um monitor específico ou uma região da tela. Também dá para manter a proporção e girar 90°, 180° ou 270°.
- **Troca de monitores**: se o monitor escolhido for desconectado, a mesa passa a cobrir todos e volta sozinha quando ele reaparece.
- **Área da mesa**: dá para usar só uma parte da superfície.
- **Curva de pressão** ajustável, com pressão mínima (limiar) e saturação.
- **12 botões da mesa**, incluindo a roda, configuráveis: atalhos de teclado, cliques ou ações como "alternar monitor".
- **Teclas multimídia** impressas na mesa (volume, tocar/pausar etc.).
- **Conexão a quente**: pode desconectar e reconectar a mesa, em qualquer porta USB, sem reiniciar nada.

Ainda não funciona: os **botões laterais da caneta** (a mesa não envia sinal deles no modo usado). Veja [`docs/STATUS.md`](docs/STATUS.md).

## Requisitos
- Linux com systemd e Python 3.11 ou mais novo.
- Testado no **Ubuntu 26.04 com GNOME (Wayland)**. Em X11, os monitores são detectados pelo `xrandr`, mas esse caminho foi menos testado.
- Os scripts de instalação usam `apt` (Ubuntu/Debian). Em outras distribuições, instale o `python3-venv` equivalente e copie `packaging/70-tomate.rules` para `/etc/udev/rules.d/` à mão.

## Instalação
```bash
git clone https://github.com/mauropn/tomateOnLinux.git
cd tomateOnLinux/MTM-1106

sudo bash scripts/setup-system.sh   # uma vez: python3-venv e regra udev
# desconecte e reconecte a mesa
bash scripts/install-user.sh        # sem sudo: ambiente Python, serviço e atalho no menu
```

Pronto: o serviço `tomate-daemon` já está rodando e passa a iniciar sozinho a cada login.

O que cada script faz:
- **`setup-system.sh`** (com sudo):
  - instala o `python3-venv`;
  - copia a regra udev, que dá ao usuário logado acesso à mesa e ao `/dev/uinput`.
- **`install-user.sh`** (sem sudo):
  - cria um ambiente Python em `.venv/` dentro da pasta e instala o projeto nele;
  - cria o serviço `systemd --user`;
  - cria o atalho **Mesa TOMATE** no menu de aplicativos.

> A pasta onde você clonou o repositório passa a ser usada pelo serviço. Não a apague nem a mova depois de instalar. Se mover, rode o `install-user.sh` de novo.

## Uso
Abra **Mesa TOMATE** no menu de aplicativos. As mudanças valem na hora, sem reiniciar nada.

| Aba | Para quê |
|---|---|
| Monitores | Escolher onde a mesa atua: todos os monitores, um monitor ou uma região |
| Área da mesa | Usar só parte da superfície, manter proporção, girar |
| Pressão | Curva de pressão, pressão mínima para clicar e saturação |
| Botões | Ação de cada botão da mesa |
| Teste | Ver a posição, a pressão e os botões em tempo real |

A configuração fica em `~/.config/tomate/config.toml`.

**Dica:** encostar a ponta na mesa é um clique. Para mover o cursor sem clicar, mantenha a caneta flutuando a poucos milímetros da superfície. Se preferir deslizar encostado, aumente a **pressão mínima** na aba Pressão.

## Problemas comuns
| Sintoma | O que fazer |
|---|---|
| A mesa não responde depois de instalar | Desconecte e reconecte a mesa. Confira o serviço: `systemctl --user status tomate-daemon` |
| `Permission denied` em `/dev/hidraw*` ou `/dev/uinput` no log | A regra udev não foi aplicada: rode `sudo bash scripts/setup-system.sh`, reconecte a mesa e faça logout/login |
| O cursor vai para o monitor errado | Escolha o monitor na aba Monitores ou use um botão com a ação "alternar monitor" |
| Quero ver o que está acontecendo | `journalctl --user -u tomate-daemon -f` |

## Desinstalar
```bash
bash scripts/uninstall-user.sh                  # remove o serviço e o atalho
sudo rm /etc/udev/rules.d/70-tomate.rules       # opcional: remove a regra udev
```
Depois, desconecte e reconecte a mesa. A configuração em `~/.config/tomate` é mantida; apague-a se quiser.

## Como funciona
O `tomate-daemon`:
1. abre a mesa via `hidraw` e envia os comandos de inicialização que o driver oficial usa: o modo de alta resolução e a área ativa da mesa inteira;
2. captura com exclusividade (*grab*) os eventos que o kernel gera para a mesa, para não haver um cursor duplicado;
3. reemite tudo por dois dispositivos virtuais `uinput`, uma caneta e um teclado/mouse, já com a configuração aplicada.

O `tomate-gui` (PySide6) edita a configuração e avisa o daemon por um socket em `$XDG_RUNTIME_DIR/tomate.sock`.

Os monitores vêm do GNOME/Mutter (D-Bus `org.gnome.Mutter.DisplayConfig`), com `xrandr` como reserva.

O protocolo está documentado em [`docs/protocolo-mtm1106.md`](docs/protocolo-mtm1106.md).

## Desenvolvimento
```bash
.venv/bin/python -m pytest              # testes (protocolo com reports reais, mapeamento, configuração)
systemctl --user stop tomate-daemon
.venv/bin/python -m tomate.daemon -v    # daemon em primeiro plano, com log detalhado
python3 re/tools/hidprobe.py listen 20  # ver os reports brutos da mesa
sudo bash scripts/setup-dev.sh          # opcional: ferramentas de engenharia reversa e captura USB
```

| Caminho | Conteúdo |
|---|---|
| `tomate/protocol.py` | Formato dos reports e comandos da mesa |
| `tomate/mapping.py` | Mesa → monitores, proporção, rotação, curva de pressão (lógica pura, testável) |
| `tomate/monitors.py` | Detecção de monitores via Mutter ou xrandr |
| `tomate/daemon.py` | Laço principal, botões, IPC |
| `tomate/device.py` | Descoberta e inicialização da mesa |
| `tomate/kernel.py` | hidraw, evdev e uinput via ioctl |
| `tomate/gui/app.py` | Interface PySide6 |
| `re/` | Descritores HID, capturas de tráfego USB e a ferramenta `hidprobe.py` |

## Aviso
Projeto independente, sem vínculo com a TOMATE ou com o fabricante da mesa. Nenhum binário, código ou pseudocódigo do driver oficial faz parte deste repositório. Use por sua conta e risco.
