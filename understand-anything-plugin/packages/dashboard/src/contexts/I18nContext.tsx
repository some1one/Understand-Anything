import { createContext, useContext, useMemo, type ReactNode } from "react";
import { getLocale, type Locale } from "../locales";

interface I18nContextValue {
  locale: Locale;
  t: Locale;
}

const I18nContext = createContext<I18nContextValue | null>(null);

export function useI18n(): I18nContextValue {
  const ctx = useContext(I18nContext);
  if (!ctx) {
    throw new Error("useI18n must be used within an I18nProvider");
  }
  return ctx;
}

export function I18nProvider({
  children,
}: {
  children: ReactNode;
}) {
  const locale = useMemo(() => getLocale(), []);

  const value = useMemo(
    () => ({
      locale,
      t: locale,
    }),
    [locale]
  );

  return (
    <I18nContext.Provider value={value}>
      {children}
    </I18nContext.Provider>
  );
}
