```instructions
---
applyTo: '**/*.ts,**/*.tsx'
---

## Code-Stil

- Verwende `type`, nicht `interface`, es sei denn, ein Interface ist für eine bestimmte Funktion erforderlich
- Verwende `export const foo = ({prop1, prop2}: Props) => {return ()}`
  - Kein Default-Export, es sei denn, die Komponente ist eine Next.js Page-Komponente oder das Framework erfordert es
  - Kein `const foo: React.FC<Props>`
  - Wenn eine Datei nur eine Komponente enthält, verwende den Namen `type Props`; verwende explizite Namen nur, wenn es mehr als eine Komponente gibt oder der Typ exportiert wird.
- Befolge die Prettier-Formatierungsdefinitionen, z.B. keine Semikolons
- Lösche vorhandene Code-Kommentare nicht, es sei denn, du änderst den Code, den sie direkt kommentieren. Wenn du es tust, aktualisiere den Kommentar stattdessen.

## Packages

- Verwende react-map-gl und maplibre für Karten. Vermeide direkten maplibre-Code, wann immer möglich. Verwende keine benutzerdefinierten Refs, sondern stattdessen den react-map-gl MapProvider.
- Verwende NUQS für URL-State-Management.
- Verwende Tailwind CSS 4 für Styling.
- Verwende Tanstack Query zum Abrufen von Daten.
- Verwende Zustand für gemeinsamen State, um Prop-Drilling zu vermeiden. Prüfe aber zuerst, ob der State nicht eher ein URL-State sein sollte.

## Chat

- Wenn es eine Folgeanfrage im Chat gibt, prüfe zunächst, ob der Benutzer Änderungen am Code manuell vorgenommen hat; überschreibe diese Änderungen nicht, sondern integriere sie.

```
