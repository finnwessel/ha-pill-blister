<p align="center"><img src="custom_components/pill_blister/brand/logo@2x.png" alt="Pill Blister" width="320"></p>

# Pill Blister

Antibabypille in Home Assistant: Blister mit Zyklus, Einnahmefenster, Einnahme-Tagebuch und Hinweise, wenn laut Beipackzettel zusätzlich verhütet werden muss. Eine Dashboard-Karte, die den Blister 1:1 abbildet, ist dabei.

> **Wichtig:** Die Integration kennt keine medizinischen Regeln. Alle Werte (Einnahmefenster, ab wann eine Pille als vergessen gilt, was dann pro Blisterwoche gilt, Erbrechen/Durchfall) werden beim Einrichten aus dem eigenen Beipackzettel übernommen. Sie zeigt nur Hinweise auf Basis dieser Angaben und behauptet nie, dass Schutz besteht. Im Zweifel: Ärztin oder Apotheke.

## Was es macht

- **Zyklus:** z. B. 21 Einnahmetage, 7 Tage Pause, ab dem Starttag des aktuellen Blisters, oder durchgehend ohne Pause (Pausentage 0, z. B. 28 Tabletten). Der Start lässt sich jederzeit über `date.<name>_pill_blister_start` ändern, die Einnahmezeit über `time.<name>_pill_dose_time`.
- **Placebotabletten:** Die letzten N Tabletten (z. B. 2 bei 26 + 2) werden eingetragen, lösen aber nie einen Hinweis aus (weder vergessen noch Erbrechen/Durchfall).
- **Einnahmefenster:** Eine Einnahme zählt für den Tag, in dessen Fenster (z. B. 2 h vorher bis 12 h nachher) sie liegt, auch nach Mitternacht. Ist das nicht eindeutig (außerhalb jedes Fensters oder der Tag ist schon eingetragen), wird **gefragt statt geraten**: `sensor.<name>_pill_pending_intake` und das Event `pill_blister_needs_assignment`, beantwortet mit `pill_blister.assign_intake`.
- **Tagebuch:** Pro Tag Uhrzeit (oder „unbekannt“), Quelle und ob nachgetragen. Pünktlichkeit wird daraus berechnet. Gespeichert in `.storage`, 400 Tage.
- **Vergessene Pille:** Kein Eintrag bis „Vergessen ab“ (z. B. 12 h nach der Einnahmezeit) oder eine noch spätere Einnahme → Hinweis „zusätzlich verhüten bis …“ mit dem Text der passenden Regel. Die Regeln gelten entweder **je Blisterwoche** (Woche 1, 2, 3) oder **je Tablettennummer** für mehrphasige Pillen wie Quelecia oder Qlaira (z. B. Tablette 1–17, 18–24, 25–26, jeweils so, wie die Tabelle im Beipackzettel es angibt). Optional eigene Regel für mehrere vergessene Pillen im selben Blister.
- **Vorzeitig neuer Blister:** Verlangt der Beipackzettel „aktuellen Blister verwerfen und sofort einen neuen beginnen“, einfach den neuen Start über `date.<name>_pill_blister_start` bzw. `start_blister` setzen. Der alte Blister bleibt im Tagebuch mit seinen Pillennummern erhalten, der Hinweis zur vergessenen Pille bleibt bestehen. Gibt es im laufenden Blister vor dem neuen Starttag noch keine Einträge, gilt das als Korrektur und ersetzt den alten Start.
- **Erbrechen, Durchfall & Co.:** Frei einrichtbare Ereignisse. Liegt eines innerhalb der eingestellten Stunden nach einer Einnahme, gibt es zuerst den Hinweis „Ersatzpille bis … möglich“; ohne Ersatzpille gilt die Regel für eine vergessene Pille oder eine eigene.
- **Zeitraum eines Hinweises:** ab der nachgeholten Einnahme bzw. ab der vergessenen Einnahmezeit bzw. ab dem Ereignis, für die eingestellte Anzahl Tage.

### Beispiel: Quelecia / Qlaira (26 + 2, durchgehend)

Einnahmetage **28**, Pausentage **0**, Placebotabletten **2**, Regeln **je Tablettennummer**. Die Bereiche, Tage und Texte stehen in der Tabelle „Pille vergessen“ des Beipackzettels und werden von dort übernommen; vorbelegt ist nichts.

## Entitäten

| Entität | Bedeutung |
|---|---|
| `sensor.<name>_pill_status` | `later` / `due` / `overdue` (gestern noch offen, Fenster läuft) / `done` / `pause` / `last_pause_day`; Attribute für die Karte (Tage, Hinweise, offene Einnahme, …) |
| `sensor.<name>_pill_pill_number` | Pille 1–21 (bzw. 1–28), in der Pause leer |
| `sensor.<name>_pill_missing_entries` | Tage im aktuellen Blister ohne Eintrag |
| `sensor.<name>_pill_last_taken` | Letzte Einnahme |
| `sensor.<name>_pill_notice_until` | Ende des längsten aktiven Hinweises |
| `sensor.<name>_pill_pending_intake` | Einnahme, die noch einem Tag zugeordnet werden muss |
| `binary_sensor.<name>_pill_due` | Ab Einnahmezeit bis zum Eintrag (auch nach Mitternacht im Fenster) |
| `binary_sensor.<name>_pill_notice` | Hinweis aktiv (Problem) |
| `button.<name>_pill_taken` | Jetzt genommen |
| `date.<name>_pill_blister_start`, `time.<name>_pill_dose_time` | Blisterstart und Einnahmezeit |
| `calendar.<name>_pill_calendar` | Tagebuch, geplante Einnahmen, Pausen und Hinweise |

## Dienste

`mark_taken` (optional `date`, `time`, `time_unknown`, `source`; liefert `{pending, day}` zurück), `remove_entry`, `assign_intake` (`date` oder `discard`), `start_blister`, `report_event` (`type`, `datetime`), `remove_event`, `mark_replacement`. Alle brauchen `config_entry_id`.

## Events

`pill_blister_due`, `pill_blister_taken` (mit `punctuality`, `deviation_min`, `in_window`, `source`), `pill_blister_missed`, `pill_blister_needs_assignment` (mit `choices` für Push-Buttons), `pill_blister_notice_started` / `_ended`, `pill_blister_entry_changed`. Erinnerungen (Push, Sprachansagen …) baut man damit als eigene Automation.

## Karte

Wird mitgeliefert und automatisch als Ressource eingetragen (`/pill_blister/pill-blister-card.js`, bei YAML-Dashboards von Hand).

```yaml
type: custom:pill-blister-card
entity: sensor.<name>_pill_status
settings_hash: "#pille-einstellungen"  # optional: Zahnrad öffnet ein Popup
```

Antippen einer Pille öffnet den Tag: Uhrzeit und Pünktlichkeit, Uhrzeit ändern, nachtragen, entfernen, Erbrechen/Durchfall melden. Das Blister-Layout lässt sich mit `columns` anpassen (Standard: eine Reihe je 7 Pillen, also 4 bei 28). Placebotabletten werden weiß dargestellt.

## Entwicklung

```bash
python3 scripts/run_pure_tests.py   # Engine-Tests ohne Home Assistant
pip install -r requirements_test.txt && pytest -q
```
