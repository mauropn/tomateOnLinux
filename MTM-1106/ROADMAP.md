# Roadmap: TOMATE MTM-1106 no Linux

Legenda: ✅ feito · 🔧 em andamento · ⬜ a fazer · 🙋 bom para quem quer contribuir

## ✅ v0.1: já funciona
**Protocolo** (engenharia reversa, documentada em [`docs/protocolo-mtm1106.md`](docs/protocolo-mtm1106.md))
- ✅ Comando de modo de alta resolução: report 9 com X/Y de 0 a 32767, pressão de 0 a 16383 e inclinação.
- ✅ Comando de área ativa em hardware. Corrige a mesa "presa na metade" quando ela guarda uma área antiga.
- ✅ Decodificação dos 12 botões expressos (atalhos de fábrica e roda) e das teclas multimídia.

**Driver** (`tomate-daemon`)
- ✅ Caneta virtual (`uinput`) com pressão e inclinação.
- ✅ Grab dos nós do kernel, sem cursor duplicado e sem "cursor fantasma".
- ✅ Mapeamento para todos os monitores, um monitor ou uma região, com proporção e rotação.
- ✅ Detecção de monitores pelo GNOME/Mutter (D-Bus), com xrandr como reserva, e reação quando um monitor é conectado ou removido.
- ✅ Curva de pressão (Bézier), limiar e saturação.
- ✅ Ações nos botões: atalho de teclado, clique, roda e alternar monitor.
- ✅ Conexão a quente, em qualquer porta USB.
- ✅ Serviço `systemd --user` que inicia no login.

**App de configuração** (`tomate-gui`, PySide6)
- ✅ Abas Monitores, Área da mesa, Pressão, Botões e Teste. As mudanças valem na hora.

**Projeto**
- ✅ 33 testes automatizados, com reports reais da mesa.
- ✅ Scripts de instalação e desinstalação, README para usuários e licença MIT.

## 🔧 v0.2: caneta completa
- 🔧 **Escala da inclinação**: a mesa manda de -127 a +127, mas a unidade não está no descritor HID. Falta medir os ângulos reais e informar a resolução ao sistema (`ABS_TILT_*`).
- ⬜ **Validar pressão e inclinação** no Krita, no GIMP e no Xournal++.
- ⬜ **Botões laterais da caneta**: a mesa não manda sinal deles no modo atual. Falta testar o modo 1 e capturar o tráfego USB no Windows com o driver oficial. 🙋 (precisa de alguém com Windows e a mesa)
- ⬜ **Inclinação na aba Teste** da GUI.

## ⬜ v0.3: uso no dia a dia
- ⬜ Testar o mapeamento para um único monitor (notebook ou externo).
- ⬜ Testar a ação "alternar monitor" num botão.
- ⬜ **Suspender e retomar**: confirmar que a mesa volta inicializada, com o modo e a área. Se não voltar, reenviar os comandos ao acordar.
- ⬜ **Rótulos dos botões na GUI** na ordem física da mesa: B1, B2, B3, B4, B6, B5, roda↑, B7, B8, roda↓, B9, B10.
- ⬜ Mostrar na GUI se a mesa está conectada e se o daemon está rodando.
- ⬜ **Perfis por aplicativo**, por exemplo atalhos diferentes no Krita e no GIMP.
- 🔧 **Pacote `.deb`** (instalação e remoção pelo apt):
  - ✅ `scripts/build-deb.sh` gera o `tomate-mtm1106_<versão>_all.deb`, com dependências pelo apt, regra udev, serviço `systemd --user` e atalho no menu;
  - ⬜ testar a instalação e a remoção numa máquina limpa;
  - ⬜ trocar a instalação por scripts pelo `.deb` como opção principal no README.

## ⬜ v0.4: distribuição
- ⬜ Releases no GitHub, com o `.deb` anexado e notas de versão.
- ⬜ Testar em outros ambientes 🙋:
  - KDE Plasma no Wayland: os monitores precisam de outra fonte além do Mutter;
  - X11;
  - Fedora e Arch.
- ⬜ Pacote para outras distribuições: AUR, RPM ou Flatpak. 🙋

## ⬜ Comunidade
- ⬜ `CONTRIBUTING.md`, com a regra de nunca enviar material do fabricante.
- ⬜ Modelos de issue (bug ou novo modelo de mesa) e de Pull Request.
- ⬜ GitHub Actions rodando os testes em cada PR.
- ⬜ Proteção da branch `main`.
- ⬜ README em inglês. 🙋

## 💡 Futuro
- 💡 **Outros modelos TOMATE**: o mesmo fabricante (SZ PENG YI, "T501") deve usar protocolos parecidos. Quem tiver outro modelo pode ajudar mandando o descritor HID e capturas feitas com `re/tools/hidprobe.py`. 🙋
- 💡 **Suporte no kernel**: propor um quirk ao `hid-uclogic` ou um driver HID pequeno que envie o modo e a área na conexão. A mesa passaria a funcionar sem o daemon, só com o suporte nativo de tablets do GNOME e do KDE.

---
Detalhes técnicos e histórico de cada item: [`docs/STATUS.md`](docs/STATUS.md). Quer ajudar? Abra uma issue dizendo em qual item quer trabalhar.
