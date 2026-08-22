#!/bin/bash
# bildschirm.sh — Desktop + Pi-Connect-Bildschirmfreigabe bei Bedarf an/aus.
#
# Der Pi laeuft dauerhaft im Konsolenbetrieb (spart ~310 MB und fast alle
# Desktop-Updates). Fuer die seltenen Faelle, in denen eine grafische Sitzung
# gebraucht wird, schaltet dieses Skript sie voruebergehend ein.
#
# WICHTIG: es aendert NICHT das Startziel. Nach einem Neustart ist der Pi
# wieder in der Konsole — man kann das Ausschalten also nicht vergessen.
#
#   bildschirm.sh an      Desktop + Freigabe starten
#   bildschirm.sh aus     beides wieder beenden
#   bildschirm.sh status  aktueller Zustand
#
# Die Handelsbots laufen in eigenen screen-Sitzungen und sind von beidem
# unberuehrt — deshalb wird gezielt der Display-Manager gestartet/gestoppt
# und nicht `systemctl isolate` verwendet (das koennte andere Dienste treffen).
set -uo pipefail

DM="lightdm"
VNC="rpi-connect-wayvnc.service"

status() {
    echo "Startziel:      $(systemctl get-default)"
    echo "Desktop ($DM):  $(systemctl is-active $DM 2>/dev/null)"
    echo "Freigabe:       $(systemctl --user is-active $VNC 2>/dev/null) / $(systemctl --user is-enabled $VNC 2>/dev/null)"
    echo "Bots:           $(screen -ls | grep -c Detached) Sitzungen"
    rpi-connect status 2>/dev/null | grep -E "Signed in|Screen sharing" | sed 's/^/  /'
}

case "${1:-status}" in
  an)
    echo "Schalte Desktop und Bildschirmfreigabe ein…"
    systemctl --user unmask "$VNC" 2>/dev/null
    sudo systemctl start "$DM" || { echo "Display-Manager liess sich nicht starten."; exit 1; }
    sleep 3
    systemctl --user start "$VNC" 2>/dev/null
    sleep 2
    echo; status
    echo
    echo "Verbinden über connect.raspberrypi.com — und danach bitte:"
    echo "  bildschirm.sh aus"
    ;;
  aus)
    echo "Schalte Bildschirmfreigabe und Desktop aus…"
    systemctl --user stop "$VNC" 2>/dev/null
    # Maskieren, damit der Dienst nicht ohne Desktop in die Neustartschleife
    # geht — genau das ist am 21.08.2026 passiert (689 Fehlversuche/Stunde).
    systemctl --user mask "$VNC" 2>/dev/null
    sudo systemctl stop "$DM" 2>/dev/null
    sleep 2
    echo; status
    ;;
  status) status ;;
  *) echo "Aufruf: bildschirm.sh an | aus | status"; exit 1 ;;
esac
