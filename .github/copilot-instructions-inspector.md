---
applyTo: './inspector/**'
---

## Code Style

- Use `type`, not `interface` unless interface required for this specific feature
- Use `export const foo = ({prop1, prop2}: Props) => {return ()}`
  - No default export, unless the component is a next js page component or the framework requires it
  - No `const foo: React.FC<Props>`
  - If a file has only one component, use the name `type Props`; only use explicit names when there is more than one component or the type is exported.
- Follow the prettier formatting defintions, eg. no semicolons
- Do not delete existing code comments unless you modify the code that they are commenting directly. If you do, rather update the comment.

## Packages

- Use react-map-gl and maplibre for maps. Avoid direct maplibre code whenever possible. Don't use custom refs but instead use the react-map-gl MapProvider.
- Use NUQS for URL state management.
- Use Tailwind CSS 4 for styling.
- Use Tanstack Query for fetching data.
- Use Zustand for shared state to avoid prop drilling. But check first if the state should rather be an URL state instead.

## Chat

- When there is a follow up request in chat, first check if the user applied changes to the code manually; do not overwrite those changes but incorporate them.
