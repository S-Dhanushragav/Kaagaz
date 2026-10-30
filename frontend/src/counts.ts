// Every "number + noun" the app shows goes through count(), with a singular and a plural form per language.
// (Hindi and Marathi drafts are MACHINE-DRAFTED like the other UI strings; English, Hindi and Marathi all use
// the singular for exactly 1 and the plural otherwise, 0 included.)
import type { Language } from './api'

export type Noun = 'step' | 'stepOpen' | 'problemFound' | 'visitOpen' | 'person' | 'secondsTaken' | 'tryLeft'

type Forms = { one: string; other: string } // {n} is the number

const FORMS: Record<Language, Record<Noun, Forms>> = {
  en: {
    step: { one: '1 step', other: '{n} steps' },
    stepOpen: { one: '1 step open', other: '{n} steps open' },
    problemFound: { one: '1 problem', other: '{n} problems' },
    visitOpen: { one: '1 office visit is still open', other: '{n} office visits are still open' },
    person: { one: '1 person', other: '{n} people' },
    secondsTaken: { one: '1 second', other: '{n} seconds' },
    tryLeft: { one: '1 try left', other: '{n} tries left' },
  },
  hi: {
    step: { one: '1 काम', other: '{n} काम' },
    stepOpen: { one: '1 काम बाकी', other: '{n} काम बाकी' },
    problemFound: { one: '1 समस्या मिली थी', other: '{n} समस्याएँ मिली थीं' },
    visitOpen: { one: 'अभी 1 बार कार्यालय जाना बाकी है', other: 'अभी {n} बार कार्यालय जाना बाकी है' },
    person: { one: '1 व्यक्ति', other: '{n} लोग' },
    secondsTaken: { one: '1 सेकंड', other: '{n} सेकंड' },
    tryLeft: { one: '1 कोशिश बाकी', other: '{n} कोशिशें बाकी' },
  },
  mr: {
    step: { one: '1 काम', other: '{n} कामे' },
    stepOpen: { one: '1 काम बाकी', other: '{n} कामे बाकी' },
    problemFound: { one: '1 अडचण आढळली', other: '{n} अडचणी आढळल्या' },
    visitOpen: { one: '1 कार्यालय भेट अजून बाकी आहे', other: '{n} कार्यालय भेटी अजून बाकी आहेत' },
    person: { one: '1 व्यक्ती', other: '{n} व्यक्ती' },
    secondsTaken: { one: '1 सेकंदात', other: '{n} सेकंदांत' },
    tryLeft: { one: '1 प्रयत्न बाकी', other: '{n} प्रयत्न बाकी' },
  },
}

export function count(language: Language, noun: Noun, n: number): string {
  const forms = FORMS[language][noun]
  return (n === 1 ? forms.one : forms.other).replace('{n}', String(n))
}
