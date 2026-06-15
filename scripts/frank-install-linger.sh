#!/bin/bash
# Esegui UNA VOLTA con sudo per abilitare Frank al boot senza login.
# sudo bash /home/ab/nanobot/scripts/frank-install-linger.sh

loginctl enable-linger ab
echo "Linger abilitato — Frank partirà al boot automaticamente."
