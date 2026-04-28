import ru from './ru';

type Primitive = string | number | boolean | null | undefined;

type Params = Record<string, Primitive>;

const getValue = (key: string): unknown => {
  return key.split('.').reduce<unknown>((acc, part) => (acc && typeof acc === 'object' ? (acc as Record<string, unknown>)[part] : undefined), ru);
};

export const t = (key: string, params?: Params): string => {
  const value = getValue(key);
  if (typeof value !== 'string') {
    if (import.meta.env.DEV) {
      // eslint-disable-next-line no-console
      console.warn(`[i18n] Missing key: ${key}`);
    }
    return key;
  }
  if (!params) return value;
  return value.replace(/\{\{\s*(\w+)\s*\}\}/g, (_, param) => `${params[param] ?? ''}`);
};

export const getI18nValue = <T,>(key: string): T => getValue(key) as T;

export { ru };
