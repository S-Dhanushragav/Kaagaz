Translate the strings of a welfare-documents app from English into {language_name} ({script} script).

The app is Kaagaz. Families in rural India use it on a phone: it checks their documents for 5 government schemes and
tells them what to fix. Many readers have little schooling, so write plain, everyday, polite {language_name}: short
sentences, common words, the words people use at a government office. Not literary, not word-for-word.

Rules:
1. Placeholders in curly braces ({member}, {document}, {documents}, {office}, {scheme}, {n}, {time}, ...) must appear
   exactly as in the source, unchanged and untranslated, each as often as in the source. Never attach a suffix or a
   case ending to a placeholder: use it as a label, for example "{member}: ..." or "{documents}: ...", and rephrase
   the sentence around it.
2. Keep digits, amounts (₹1,500), dates, and these unchanged: SPECIMEN, SAM 3.1, Muse Spark, MMS-TTS, SMS, PDF, LPG.
3. The app's name is written exactly {brand} in {language_name}.
4. Use exactly these terms:
{glossary}
5. Other schemes or places: do not add any. Do not add or drop any fact, number, condition or warning.
6. Arrays of strings are separate items; translate each item.
7. Keys "counts.<noun>.one" are used for exactly 1 and "counts.<noun>.other" for every other number ({n}): use the
   right grammatical number for each.
8. Keys starting with "voice." are shown on screen and also read aloud by a text-to-speech voice: write them so they
   sound natural when read out. Keep the punctuation of the source: the colon after a label ("{member}: ...",
   "Fee: {fee}") and the full stop at the end of each sentence.

Reply with one JSON object only: the same keys, each with its {language_name} translation.

Strings (JSON, key -> English):
{items}
