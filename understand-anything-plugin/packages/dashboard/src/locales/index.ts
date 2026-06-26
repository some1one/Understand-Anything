import en from "./en";

export type Locale = typeof en;

export function getLocale(): Locale {
  return en;
}

export { en };
