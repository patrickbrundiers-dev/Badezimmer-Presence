# Badezimmer Presence

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-orange.svg)](https://hacs.xyz)
[![Validate](https://github.com/patrickbrundiers-dev/Badezimmer-Presence/actions/workflows/validate.yml/badge.svg)](https://github.com/patrickbrundiers-dev/Badezimmer-Presence/actions/workflows/validate.yml)

Zuverlässige Belegterkennung fürs Badezimmer als Home-Assistant-Integration.
Sie kombiniert Präsenzsensor, Eintrittssensor, Türkontakt, Klodeckel und
Luftfeuchtigkeit zu einem einzigen „Bad belegt“-Zustand, erkennt Duschen und
WC-Nutzung und führt eine Nutzungsstatistik.

Die Integration ersetzt ein Paket aus zwölf Automationen und rund fünfzehn
Helfern durch ein Gerät, das komplett über die Oberfläche eingerichtet wird.

## Installation

1. HACS öffnen, oben rechts **⋮ → Benutzerdefinierte Repositories**.
2. `https://github.com/patrickbrundiers-dev/Badezimmer-Presence` mit Typ **Integration** hinzufügen.
3. **Badezimmer Presence** installieren und Home Assistant neu starten.
4. **Einstellungen → Geräte & Dienste → Integration hinzufügen → Badezimmer Presence**.

Pro Badezimmer wird ein Eintrag angelegt, mehrere Bäder sind möglich.

## Sensoren

| Sensor | Pflicht | Wofür |
|---|---|---|
| Präsenzsensor (Raum) | ja | mmWave/PIR im Bad. Hält den Raum belegt und gibt ihn frei. |
| Eintrittssensor | nein | Bewegungsmelder an der Tür. Startet das Eintrittsfenster. |
| Türkontakt | nein | Schnellfreigabe beim Verlassen. Ersetzt den Eintrittssensor, wenn keiner da ist. |
| Klodeckel-Kontakt | nein | Offener Deckel bedeutet eindeutige Nutzung. |
| Luftfeuchtigkeit | nein | Duscherkennung über den Feuchte-Anstieg (%/min). |

Die Sensoren lassen sich später über **⋮ → Neu konfigurieren** ändern, alle
Zeiten und Schwellwerte über **Konfigurieren**.

## So funktioniert die Erkennung

**Belegt** wird das Bad, wenn

* Eintritt und Präsenz innerhalb des Eintrittsfensters (Standard 60 s) zusammenkommen, egal in welcher Reihenfolge, oder
* eine eindeutige Nutzung erkannt wird: Klodeckel geht auf oder eine Dusche startet.

Präsenz allein reicht nicht, damit der Sensor nicht durch die offene Tür aus
dem Flur auslöst. Ohne Eintritts- und Türsensor reicht Präsenz allein.

**Freigegeben** wird das Bad über einen dieser Wege:

| Weg | Bedingung | Standard |
|---|---|---|
| Normal | Keine Präsenz für X, keine Dusche, Deckel zu, kein Eintrittsfenster aktiv | 3 min |
| Schnellfreigabe | Tür geht auf, danach verschwindet die Präsenz innerhalb von 60 s und kommt in den folgenden 20 s nicht zurück (Spiegel-/Wiedereintrittsschutz) | 60 s / 20 s |
| Notbremse | Länger als X belegt und mindestens Y keine Präsenz, auch bei offenem Deckel oder hängender Dusche | 120 min / 5 min |
| Neustart-Check | Nach dem Start von Home Assistant ist niemand im Raum | 1 min nach Start |
| Manuell | Button **Freigeben** oder Dienst `badezimmer_presence.release` | |

**Dusche** an, wenn die Luftfeuchtigkeit über das Zeitfenster (3 min) um mehr
als 0,7 %/min steigt, und das mindestens 1 min lang. Aus, wenn der Anstieg
5 min lang unter 0,15 %/min liegt oder die maximale Duschdauer (60 min)
erreicht ist. Eine Dusche hält das Bad belegt, auch wenn der Radar die Person
hinter der Glaswand verliert.

## Entitäten

| Entität | Beschreibung |
|---|---|
| `binary_sensor.<bad>_belegt` | Hauptzustand. Attribute: `occupied_since`, `occupy_reason`, `last_release_reason` |
| `binary_sensor.<bad>_dusche` | Dusche läuft |
| `binary_sensor.<bad>_nutzung_erkannt` | Seit dem Belegen wurde geduscht oder der Deckel geöffnet |
| `binary_sensor.<bad>_klodeckel_zu_lange_offen` | Problem-Sensor, Deckel länger als 40 min offen |
| `binary_sensor.<bad>_eintrittsfenster` | Diagnose: Eintrittsfenster läuft |
| `sensor.<bad>_status` | Frei, Eintritt erkannt, Belegt, Warte auf Freigabe, WC, Duschen, Sensorfehler |
| `sensor.<bad>_feuchte_anstieg` | Diagnose: aktueller Anstieg in %/min |
| `sensor.<bad>_{nutzung,dusche,wc}_anzahl` | Zähler (total_increasing) |
| `sensor.<bad>_{nutzung,dusche,wc}_minuten_gesamt` | Gesamtminuten (total_increasing) |
| `sensor.<bad>_{nutzung,dusche,wc}_letzte_dauer` | Dauer der letzten Nutzung |
| `sensor.<bad>_{nutzung,dusche,wc}_maximale_dauer` | Längste Nutzung |
| `sensor.<bad>_{nutzung,dusche,wc}_durchschnittsdauer` | Durchschnitt über alle Nutzungen |
| `sensor.<bad>_{nutzung,dusche,wc}_anzahl_{heute,woche,monat}` | Anzahl im laufenden Tag / Woche / Monat |
| `sensor.<bad>_{nutzung,dusche,wc}_minuten_{heute,woche,monat}` | Minuten im laufenden Zeitraum |
| `sensor.<bad>_{nutzung,dusche,wc}_durchschnitt_{heute,woche,monat}` | Durchschnittsdauer im laufenden Zeitraum |
| `sensor.<bad>_{nutzung,dusche,wc}_start` | Beginn der laufenden bzw. letzten Nutzung (ersetzt die `input_datetime`-Helfer) |
| `switch.<bad>_belegt_manuell` | Bad von Hand belegen oder freigeben (ersetzt das `input_boolean`) |
| `button.<bad>_freigeben` | Bad sofort freigeben |

`<bad>` ist der beim Einrichten vergebene Name. Gibt es schon eine Entität mit
derselben ID (z. B. den alten Template-Sensor `binary_sensor.badezimmer_belegt`),
hängt Home Assistant `_2` an. Wähle dann einen anderen Namen oder benenne um,
sobald die alten Helfer entfernt sind.

Tages-, Wochen- und Monatswerte liefert die Integration selbst, Verbrauchszähler-Helfer
sind nicht mehr nötig. Die Woche beginnt am Montag.

## Ereignisse für Benachrichtigungen

Die Integration feuert `badezimmer_presence_event` mit dem Feld `type`:
`occupied`, `released` (mit `reason` und `duration_minutes`), `shower_started`,
`shower_ended` und `toilet_lid_alert`.

Beispiel, das die bisherige Klodeckel-Benachrichtigung ersetzt:

```yaml
alias: Bad - Klodeckel offen Hinweis
triggers:
  - trigger: event
    event_type: badezimmer_presence_event
    event_data:
      type: toilet_lid_alert
actions:
  - action: notify.mobile_app_patrick
    data:
      title: Badezimmer
      message: "Der Klodeckel ist seit {{ trigger.event.data.minutes }} Minuten offen."
  - action: notify.send_message
    target:
      entity_id: notify.wohnzimmer_sprechen
    data:
      message: Der Klodeckel ist noch offen, bitte schließen.
mode: single
```

## Umstieg von den bisherigen Automationen

1. Integration einrichten mit
   * Präsenz: `binary_sensor.bad_prasenz_presence`
   * Eintritt: `binary_sensor.bad_eintritt_occupancy`
   * Tür: `binary_sensor.baderzimmer_tur_gr_contact`
   * Klodeckel: `binary_sensor.klodeckel_contact`
   * Luftfeuchtigkeit: `sensor.badezimmer_dusche_humidity`
2. Bisherige Statistik übernehmen (in **Entwicklerwerkzeuge → Aktionen** im YAML-Modus, Gerät auswählen):

   ```yaml
   action: badezimmer_presence.set_statistics
   data:
     device_id: <Gerät „Badezimmer“>
     kind: usage
     count: "{{ states('input_number.bad_nutzungen_gesamt_speicher') | int }}"
     total_minutes: "{{ states('input_number.bad_nutzungsminuten_gesamt_speicher') | float }}"
     last_minutes: "{{ states('input_number.bad_letzte_dauer') | float }}"
     max_minutes: "{{ states('input_number.bad_max_dauer') | float }}"
   ```

   Die laufenden Zeiträume übernimmst du mit `today_count`, `today_minutes`, `week_count`,
   `week_minutes`, `month_count` und `month_minutes` im selben Aufruf.

   Dasselbe mit `kind: shower` (`bad_duschen_gesamt_speicher`, `bad_duschminuten_gesamt_speicher`,
   `bad_dusche_letzte_dauer`, `bad_dusche_max_dauer`) und `kind: toilet`
   (`bad_wc_nutzungen_gesamt_speicher`, `bad_wc_minuten_gesamt_speicher`,
   `bad_wc_letzte_dauer`, `bad_wc_max_dauer`).
3. Ein paar Tage parallel laufen lassen und `sensor.badezimmer` mit dem neuen Status-Sensor vergleichen.
4. Automationen, die `binary_sensor.badezimmer_belegt` nutzen (z. B. „Badezimmerlicht neu“), auf den neuen Belegt-Sensor umstellen.
5. Die alten Automationen deaktivieren: Entry Fenster starten, Entry Timer stoppen, Belegt setzen, Freigeben,
   Schnell freigeben bei Exit, Maximale Belegungszeit Notbremse, Neustart Check, Nutzung erkannt,
   Dusche EIN/AUS, Klodeckel 40 Minuten offen und die sechs Statistik-Automationen.
   Danach können der Timer, die `input_boolean`-, `input_datetime`- und `input_number`-Helfer, der
   Ableitungssensor „Dusche“ und die Template-Sensoren weg.

## Was gegenüber den Automationen besser ist

* **Exakte Zeiten statt Polling:** Freigabe und Notbremse laufen auf die Sekunde, statt per Minuten- bzw. 5-Minuten-Watchdog.
* **Maximale Duschdauer:** Eine hängende Dusche (Feuchte bleibt hoch) blockiert das Bad nicht mehr bis zur Notbremse.
* **Freigabegrund und Belegungsgrund** als Attribute, damit sich Fehlerkennungen nachvollziehen lassen.
* **Mehr Statistik:** Maximal- und Durchschnittsdauer für Nutzung, Dusche und WC, als Langzeitstatistik nutzbar.
* **Ereignisse** statt fest verdrahteter Benachrichtigungen.
* **Fallbacks:** funktioniert auch nur mit Präsenzsensor oder mit Türkontakt statt Eintrittssensor.
* **Neustartfest:** Zustand und Statistik werden gespeichert, der Neustart-Check ist eingebaut.
* **Alles einstellbar** über die Oberfläche, mehrere Bäder möglich.

## Entwicklung

```bash
pip install -r requirements_test.txt ruff
ruff check custom_components tests
pytest
```

Die Logik steckt in `custom_components/badezimmer_presence/engine.py` und ist
ohne laufendes Home Assistant testbar (`tests/test_engine.py`).
