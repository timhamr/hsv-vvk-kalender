# HSV Spiele & Mitglieder-Vorverkauf als Kalender

Liest alle 6 Stunden die Termintabelle auf [hsv.de/tickets/ticketinfos](https://www.hsv.de/tickets/ticketinfos)
und veröffentlicht sie als abonnierbaren Kalender:

**https://timhamr.github.io/hsv-vvk-kalender/hsv.ics**

- ⚽ alle Heim- und Auswärtsspiele (noch nicht terminierte Spieltage als ganztägiger Zeitraum)
- 🎟️ jeder angekündigte Mitglieder-Vorverkauf, mit Erinnerung 30 Minuten vorher (Pre-Warteraum)

In Proton Calendar: **+** neben „Meine Kalender“ → „Kalender über URL hinzufügen“ → Link einfügen.

`python3 build.py` erzeugt `docs/hsv.ics` lokal; `python3 build.py seite.html` liest eine gespeicherte Seite.
Inoffiziell, kein Angebot des Hamburger SV.
