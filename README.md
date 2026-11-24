# Aktien-Scanner

Durchsucht ein Welt-Aktienuniversum und erstellt Ranglisten nach **Bewertung, Qualität, Momentum und Dividende** – mit grafischer Oberfläche, ohne Kommandozeile im Alltag.

> **Handelt nicht.** Kein Broker, keine Orders. Ergebnisse sind Entwicklungsdaten, keine Anlageberatung.

Stand: Subphase A (Grundgerüst). Die Oberfläche startet; Datenabruf, Kennzahlen und Ranglisten folgen in den Subphasen B–D.

## Einmalige Einrichtung (Windows mit WSL2/Ubuntu 24.04)

Alle Befehle im **Ubuntu-Fenster** (Startmenü → „Ubuntu“) eingeben.

**1. GitHub-Zugang für Ubuntu einrichten** (das Repo ist privat)

```bash
sudo apt install -y gh
gh auth login
```

Bei den Fragen wählen: `GitHub.com` → `HTTPS` → Git mit GitHub-Zugang anmelden: `Yes` → `Login with a web browser`. Den angezeigten Code im Browser eingeben.

**2. Projekt holen und installieren**

```bash
gh repo clone MrHamcom/aktien-scanner ~/aktien-scanner
~/aktien-scanner/install.sh
```

Das Skript
- installiert fehlende Systempakete (fragt einmal nach dem Ubuntu-Passwort),
- legt die Python-Umgebung an und installiert alle Abhängigkeiten,
- führt einen Selbsttest aus,
- legt auf dem Windows-Desktop die Verknüpfung **„Aktien-Scanner“** an.

## Bedienung

- **Starten:** Doppelklick auf „Aktien-Scanner“ auf dem Desktop. Der Browser öffnet sich mit der Oberfläche (`http://localhost:8765`).
- **Beenden:** Das minimierte Fenster „Aktien-Scanner“ in der Taskleiste schließen.
- **Aktualisieren** (wenn Claude eine neue Version bereitgestellt hat): im Ubuntu-Fenster `~/aktien-scanner/update.sh`.
- **Daten laden:** Übersicht → Umfang wählen → „Lauf starten“. Hochlauf in drei Stufen:
  1. *Probe 100* – 60 US- und 40 deutsche Aktien (größte Gewichte), ca. 10 Minuten
  2. *Probe 500* – 100 je Region, ca. 45 Minuten
  3. *Vollständig* – alle Aktien der Startliste, mehrere Stunden (über Nacht)
- **Abbrechen / Fortsetzen:** Ein abgebrochener oder wegen Abrufsperren gestoppter Lauf lässt sich in der Übersicht fortsetzen; bereits geladene Daten werden nicht erneut abgerufen. Das gilt auch, wenn das Programm während eines Laufs geschlossen wurde.
- **Datenqualität:** zeigt je Region, wie viele Aktien vollständige Daten haben, und warum etwas fehlt (unbekannter Ticker, Börse ohne Zuordnung, keine Daten).

## Aufbau

```
config/scanner.yaml   Regeln, Schwellen, Gewichte (einzige Stelle für Einstellungen)
src/scanner/core/     Rechen-Engine – kennt die Oberfläche nicht
src/scanner/ui/       Oberfläche (NiceGUI)
src/scanner/cli.py    Hilfsbefehle (scanner check, scanner run --scope probe_100)
config/exchanges.yaml Börsenname → Yahoo-Tickerformat
tests/                Unit-Tests
install.sh            einmalige Einrichtung
start.sh              Start (wird von der Desktop-Verknüpfung aufgerufen)
update.sh             neue Version holen
data/                 Datenbank, Cache (nicht im Repo)
exports/              CSV-Exporte (nicht im Repo)
```

## Fehlersuche

| Problem | Lösung |
|---|---|
| Browser öffnet sich nicht | `http://localhost:8765` selbst im Browser öffnen |
| Seite nicht erreichbar | Fenster „Aktien-Scanner“ in der Taskleiste öffnen und Fehlermeldung ansehen |
| Selbsttest schlägt fehl | Ausgabe von `~/aktien-scanner/.venv/bin/scanner check` an Claude schicken |
| Startliste lässt sich nicht laden | Holdings-CSV des iShares MSCI ACWI ETF (ACWI) auf ishares.com über „Detaillierte Positionen“ herunterladen und als `~/aktien-scanner/data/start_list.csv` speichern – die Datei hat Vorrang vor dem Download |
| „Yahoo sperrt die Abrufe“ | Lauf ist gestoppt, nicht verloren. Einige Stunden warten, dann „Fortsetzen“ |
| Viele „Börse ohne Zuordnung“ | Seite Datenqualität als Screenshot an Claude schicken – die Zuordnung in `config/exchanges.yaml` wird ergänzt |
