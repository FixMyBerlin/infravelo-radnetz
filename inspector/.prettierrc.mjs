// @ts-check
/** @type {import("prettier").Config} */
const prettierConfig = {
  semi: false,
  singleQuote: true,
  arrowParens: 'always',
  printWidth: 100,
  plugins: ['prettier-plugin-organize-imports', 'prettier-plugin-tailwindcss'],
  tailwindAttributes: ['positionClasses', 'classNameOverwrite'],
  tailwindFunctions: ['twMerge', 'clsx', 'twJoin'],
}

export default prettierConfig
