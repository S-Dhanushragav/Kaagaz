# Phase 11 translation report (Tamil, Telugu, Kannada)

Pipeline: `scripts/translate.py`. Muse Spark (`muse-spark-1.3`, Meta Model API) translated every UI string and template
from English with a fixed glossary; Muse Spark Open (Baseten) back-translated each string literally and then compared
its meaning with the English source; code checked placeholders, numbers, the app's name, punctuation and script.
Reviewed corrections live in `data/translations/fixes.yaml` and are back-translated and checked again on every run.
Reviewer: Claude Code, not a native speaker: clear errors were fixed, uncertain ones are listed, nothing was guessed.
All three languages are marked machine-translated in the app.

One run was thrown away before review: the first prompt asked for spoken templates 'with no symbols', and Muse Spark
dropped every colon and full stop from the plan sentences (no check failed: placeholders and numbers were intact).
The prompt now keeps punctuation and a code check fails on dropped punctuation.

| Language | Strings | First pass: code failures | First pass: meaning mismatches | Fixed | Final: code | Final: meaning |
|---|---|---|---|---|---|---|
| Tamil | 362 | 0 | 10 | 8 | 0 | 6 |
| Telugu | 362 | 1 | 5 | 12 | 1 | 1 |
| Kannada | 362 | 1 | 3 | 6 | 0 | 0 |

## Tamil

First pass `translation_ta_20261101-130451.json`, final `translation_ta_20261101-133013.json`.

### Every mismatch in the first pass

| Key | English | Back-translation | Check | Outcome |
|---|---|---|---|---|
| `ui.tagline` | Check your family's welfare documents and get a plan to fix problems. | Check your family documents. Learn how to fix problems. | Drops 'welfare' and changes 'get a plan to fix problems' to generic 'learn how to fix problems'. | fixed: dropped 'welfare' and 'a plan' |
| `ui.noDocuments` | No documents were found. Add photos of your papers, or record them again. | No documents found. Add photos of your papers, or register again. | changes action from recording documents again to registering again | fixed: பதிவு செய்யவும் also reads as 'register': 'record a video again' |
| `ui.schemeNote` | Rules from official sources. Kaagaz checks your documents; it does not apply for you. | Rules taken from government information. Caucus will check your documents. Will not apply for you. | App name Kaagaz mistranslated as Caucus. | false alarm: back-translation of the app's name (காகஸ் read as 'Caucus'), not an error |
| `ui.howTitle` | How Kaagaz works | How Caucus works | App name Kaagaz mistranslated as Caucus. | false alarm: back-translation of the app's name (காகஸ் read as 'Caucus'), not an error |
| `ui.askShort` | Ask Kaagaz | Ask Caucus | Product name Kaagaz mistranslated as Caucus. | false alarm: back-translation of the app's name (காகஸ் read as 'Caucus'), not an error |
| `ui.askError` | Kaagaz could not answer right now. Please try again. | Caucus cannot answer now. Please try again. | Product name Kaagaz mistranslated as Caucus. | false alarm: back-translation of the app's name (காகஸ் read as 'Caucus'), not an error |
| `ui.consent` | Kaagaz saves your family's check results so you can come back to them. Delete anytime. | Cacus will save your family's verification results. You can come later and see. You can delete anytime you want. | Product name Kaagaz mistranslated as Cacus. | false alarm: back-translation of the app's name (காகஸ் read as 'Caucus'), not an error |
| `reasons.reasons.age.doubtful` | The date of birth differs between documents. | Date of birth is different in every document. | Source says DOB differs between documents, back says different in every document. | fixed: said 'different in every document' |
| `voice.procedures.caste_certificate_new` | {member}: apply to the {office} for a caste certificate. Start this first; it takes the longest. {caution} | {member}: Place to apply for caste certificate: {office}. Start this first; it takes many days. {caution} | Source says it takes the longest, back says it takes many days, losing the superlative comparison. | fixed: lost 'it takes the longest' |
| `voice.values.16` | Acceptance of the declaration is up to the office. | The office will decide whether to accept the affidavit or not. | Source says declaration, back says affidavit, which is a different legal document. | flagged: உறுதிமொழி கடிதம் is the usual word for a written declaration; back-translated as 'affidavit'. Left as is. |

### Fixed on review (not flagged by the checks)

| Key | First translation | Fix | Why |
|---|---|---|---|
| `ask.suggestions.name_mismatch` | {member}: பெயர் எழுத்துப் பிழை உள்ளது. என்ன செய்வது? | {member}: பெயர் ஆவணங்களில் வேறு வேறு எழுத்துக்கூட்டலில் உள்ளது. என்ன செய்வது? | said the name has a spelling mistake; the app only knows the spellings differ |
| `voice.card_member` | {n}: ரேஷன் அட்டையில் உள்ள உறுப்பினர் | ரேஷன் அட்டையில் உறுப்பினர் எண் {n} | read as '{n}: a member on the ration card' |
| `counts.stepOpen.one` | 1 படி திறந்திருக்கிறது | 1 படி மீதம் உள்ளது | '1 step is open' (literal) |
| `counts.stepOpen.other` | {n} படிகள் திறந்திருக்கின்றன | {n} படிகள் மீதம் உள்ளன | 'steps are open' (literal) |

### Still flagged in the final run

- `ui.schemeNote`: App name Kaagaz mistranslated as Caucus.
- `ui.howTitle`: App name Kaagaz mistranslated as Caucus.
- `ui.askShort`: Product name Kaagaz mistranslated as Caucus.
- `ui.askError`: Product name Kaagaz mistranslated as Caucus.
- `ui.consent`: Product name Kaagaz mistranslated as Cacus.
- `voice.values.16`: changes 'declaration' to 'affidavit', a different document type

### Scheme names and spoken numbers

Scheme names (transliterated official names; the app shows the English name in brackets after the full name and
at the first mention in a reply):

- ladki_bahin: முக்யமந்திரி மாஜி லாட்கி பஹிண் யோஜனா / short லாட்கி பஹிண்
- pm_ujjwala: பிரதான்மந்திரி உஜ்ஜ்வலா யோஜனா / short உஜ்ஜ்வலா
- ramai_awas: ரமாய் ஆவாஸ் யோஜனா / short ரமாய்
- sanjay_gandhi_niradhar: சஞ்சய் காந்தி நிராதார் அனுதான் யோஜனா / short சஞ்சய் காந்தி
- shravanbal: ஷ்ராவண்பாள் சேவா ராஜ்ய நிவ்ருத்திவேதன் யோஜனா / short ஷ்ராவண்பாள்

Number words 0-99 (spot-checked: 0-25 and 90-99), hundreds `நூறு, இருநூறு, முந்நூறு, நாநூறு, ஐந்நூறு, அறுநூறு, எழுநூறு, எண்ணூறு, தொள்ளாயிரம்`, thousand `ஆயிரம்`,
years `{n} நூறு`, months `ஜனவரி, பிப்ரவரி, மார்ச், ஏப்ரல், மே, ஜூன், ஜூலை, ஆகஸ்ட், செப்டம்பர், அக்டோபர், நவம்பர், டிசம்பர்`.

## Telugu

First pass `translation_te_20261101-130929.json`, final `translation_te_20261101-133022.json`.

### Every mismatch in the first pass

| Key | English | Back-translation | Check | Outcome |
|---|---|---|---|---|
| `ui.tagline` | Check your family's welfare documents and get a plan to fix problems. | Look after your family documents. If there are mistakes, learn how to correct them. | Omits 'welfare' and changes 'check' to 'look after'. | fixed: dropped 'welfare' and 'a plan'; 'check' read as 'look after' |
| `ui.stages.build_household` | Matching people | We are adding people | Changes 'matching people' to 'adding people'. | fixed: said 'adding people', not matching |
| `ui.issueTypes.expired` | Certificate may be too old | Certificate may be very old | Source warns certificate may be too old to be valid, back says only very old without implying expiry. | fixed: said 'very old', not 'too old' |
| `ui.loginTitle` | Log in to keep your checks | Login to keep your observations safe | 'checks' (eligibility checks) mistranslated as 'observations' | flagged: పరిశీలనలు ('examinations') is the word used for 'check' throughout; back-translated as 'observations'. Left as is. |
| `voice.values.6` | Proof of date of birth (e.g. birth certificate) | Proof of date of birth (for example birth certificate) | punctuation dropped | false alarm: the source's only full stops are in 'e.g.' |
| `scheme.shravanbal.benefit` | Monthly pension for people 65 and over | Monthly pension for those who have crossed 65 years | Back-translation requires age over 65, source includes 65 and over. | fixed: said 'over 65'; the rule is 65 and over |

### Fixed on review (not flagged by the checks)

| Key | First translation | Fix | Why |
|---|---|---|---|
| `voice.ask_at_office.name_mismatch` | {member}: పత్రాలు: {documents}. వీటిలో పేరు వేరుగా ఉంది. మిగతా పత్రాలలో పేరు వేరుగా ఉంది. కార్యాలయం లో ఏమి చేయాలో అడగండి. | {member}: పత్రాలు: {documents}. వీటిలో పేరు స్పెల్లింగ్ వారి మిగతా పత్రాల కంటే వేరుగా ఉంది. ఏమి చేయాలో కార్యాలయంలో అడగండి. | the same sentence twice |
| `voice.card_member` | రేషన్ కార్డులో ఉన్న సభ్యుడు: {n} | రేషన్ కార్డులో సభ్యుడు నంబర్ {n} | read as 'member on the ration card: {n}' |
| `counts.stepOpen.one` | 1 దశ తెరిచి ఉంది | 1 పని మిగిలి ఉంది | '1 step is open' (literal) |
| `counts.stepOpen.other` | {n} దశలు తెరిచి ఉన్నాయి | {n} పనులు మిగిలి ఉన్నాయి | 'steps are open' (literal) |
| `counts.tryLeft.one` | 1 ప్రయత్నం మిగిలి ఉంది. | 1 ప్రయత్నం మిగిలి ఉంది | a full stop inside a count |
| `counts.tryLeft.other` | {n} ప్రయత్నాలు మిగిలి ఉన్నాయి. | {n} ప్రయత్నాలు మిగిలి ఉన్నాయి | a full stop inside a count |
| `counts.visitOpen.one` | 1 కార్యాలయం సందర్శన ఇంకా మిగిలి ఉంది | 1 కార్యాలయ సందర్శన ఇంకా మిగిలి ఉంది | కార్యాలయం సందర్శన: the compound takes కార్యాలయ |
| `counts.visitOpen.other` | {n} కార్యాలయం సందర్శనలు ఇంకా మిగిలి ఉన్నాయి | {n} కార్యాలయ సందర్శనలు ఇంకా మిగిలి ఉన్నాయి | కార్యాలయం సందర్శనలు: the compound takes కార్యాలయ |

### Still flagged in the final run

- `ui.loginTitle`: 'checks' (eligibility checks) mistranslated as 'observations'
- `voice.values.6`: punctuation dropped

### Scheme names and spoken numbers

Scheme names (transliterated official names; the app shows the English name in brackets after the full name and
at the first mention in a reply):

- ladki_bahin: ముఖ్యమంత్రి మాఝీ లాడ్కీ బహీణ్ యోజన / short లాడ్కీ బహీణ్
- pm_ujjwala: ప్రధానమంత్రి ఉజ్జ్వలా యోజన / short ఉజ్జ్వలా
- ramai_awas: రమాయి ఆవాస్ యోజన / short రమాయి
- sanjay_gandhi_niradhar: సంజయ్ గాంధీ నిరాధార్ అనుదాన్ యోజన / short సంజయ్ గాంధీ
- shravanbal: శ్రావణ్‌బాళ్ సేవా రాజ్య నివృత్తివేతన్ యోజన / short శ్రావణ్‌బాళ్

Number words 0-99 (spot-checked: 0-25 and 90-99), hundreds `వంద, రెండు వందలు, మూడు వందలు, నాలుగు వందలు, ఐదు వందలు, ఆరు వందలు, ఏడు వందలు, ఎనిమిది వందలు, తొమ్మిది వందలు`, thousand `వేలు`,
years `{n} వందల`, months `జనవరి, ఫిబ్రవరి, మార్చి, ఏప్రిల్, మే, జూన్, జూలై, ఆగస్టు, సెప్టెంబర్, అక్టోబర్, నవంబర్, డిసెంబర్`.

## Kannada

First pass `translation_kn_20261101-131416.json`, final `translation_kn_20261101-133022.json`.

### Every mismatch in the first pass

| Key | English | Back-translation | Check | Outcome |
|---|---|---|---|---|
| `ui.issueTypes.expired` | Certificate may be too old | Certificate may be old | Back says 'may be old' instead of 'may be too old', losing the expiry/too-old warning. | fixed: said 'may be old', not 'too old' |
| `ui.unidentifiedMany` | {n} more items looked like documents but couldn't be read. Add a photo of any that is a document. | {n} items looked like documents. But could not be read. Whichever of them is a document add photo. | Dropped 'more' so additional items reads as total items | fixed: dropped 'more': read as the total |
| `ask.chips.unknown` | paper not identified | Could not know which paper it is | the app's name is misspelled | rule changed: ಕಾಗದ is Kannada for 'paper', no longer treated as a misspelt app name |
| `scheme.shravanbal.benefit` | Monthly pension for people 65 and over | Monthly pension for those above 65 years | Back excludes 65-year-olds, source includes 65 and over. | fixed: said 'above 65'; the rule is 65 and over |

### Fixed on review (not flagged by the checks)

| Key | First translation | Fix | Why |
|---|---|---|---|
| `ui.tagline` | ನಿಮ್ಮ ಮನೆಯ ದಾಖಲೆಗಳನ್ನು ಪರಿಶೀಲಿಸಿ. ತಪ್ಪು ಸರಿಪಡಿಸಲು ಏನು ಮಾಡಬೇಕೆಂದು ತಿಳಿಯಿರಿ. | ನಿಮ್ಮ ಕುಟುಂಬದ ಕಲ್ಯಾಣ ದಾಖಲೆಗಳನ್ನು ಪರಿಶೀಲಿಸಿ, ಸಮಸ್ಯೆಗಳನ್ನು ಸರಿಪಡಿಸಲು ಮಾಡಬೇಕಾದ ಕೆಲಸಗಳ ಪಟ್ಟಿ ಪಡೆಯಿರಿ. | dropped 'welfare' and 'a plan' |
| `voice.law_sets` | ಈ ಕಚೇರಿಗೆ ಕಾನೂನಿನಲ್ಲಿ ಇರುವ ಸಮಯ: {time_limit}. | ಕಾನೂನು ಈ ಕಚೇರಿಗೆ {time_limit} ಸಮಯ ನೀಡಿದೆ. | read as 'the time in the law for this office'; a time limit is only said as 'the law sets ... for this office' |
| `voice.procedures.income_certificate_new` | ಹೊಸ ಆದಾಯ ಪ್ರಮಾಣಪತ್ರಕ್ಕೆ ಆಪ್ಲೆ ಸರ್ಕಾರ್ ಪೋರ್ಟಲ್ ನಲ್ಲಿ ಅಥವಾ ಆಪ್ಲೆ ಸರ್ಕಾರ್ ಸೇವಾ ಕೇಂದ್ರದಲ್ಲಿ ಅರ್ಜಿ ಕೊಡಿ. ಕೊಡುವ ಕಚೇರಿ: {office}. ಕಾನೂನಿನಲ್ಲಿ ಇರುವ ಸಮಯ: {time_limit}. | ಹೊಸ ಆದಾಯ ಪ್ರಮಾಣಪತ್ರಕ್ಕೆ ಆಪ್ಲೆ ಸರ್ಕಾರ್ ಪೋರ್ಟಲ್‌ನಲ್ಲಿ ಅಥವಾ ಆಪ್ಲೆ ಸರ್ಕಾರ್ ಸೇವಾ ಕೇಂದ್ರದಲ್ಲಿ ಅರ್ಜಿ ಕೊಡಿ. ಕೊಡುವ ಕಚೇರಿ: {office}. ಕಾನೂನು ಈ ಕಚೇರಿಗೆ {time_limit} ಸಮಯ ನೀಡಿದೆ. | the time limit must be said exactly as voice.law_sets (tests/test_voice.py) |

### Still flagged in the final run

- none

### Scheme names and spoken numbers

Scheme names (transliterated official names; the app shows the English name in brackets after the full name and
at the first mention in a reply):

- ladki_bahin: ಮುಖ್ಯಮಂತ್ರಿ ಮಾಝಿ ಲಾಡಕಿ ಬಹಿಣ್ ಯೋಜನಾ / short ಲಾಡಕಿ ಬಹಿಣ್
- pm_ujjwala: ಪ್ರಧಾನಮಂತ್ರಿ ಉಜ್ಜ್ವಲಾ ಯೋಜನಾ / short ಉಜ್ಜ್ವಲಾ
- ramai_awas: ರಮಾಯಿ ಆವಾಸ್ ಯೋಜನಾ / short ರಮಾಯಿ
- sanjay_gandhi_niradhar: ಸಂಜಯ್ ಗಾಂಧಿ ನಿರಾಧಾರ್ ಅನುದಾನ್ ಯೋಜನಾ / short ಸಂಜಯ್ ಗಾಂಧಿ
- shravanbal: ಶ್ರಾವಣಬಾಳ್ ಸೇವಾ ರಾಜ್ಯ ನಿವೃತ್ತಿವೇತನ್ ಯೋಜನಾ / short ಶ್ರಾವಣಬಾಳ್

Number words 0-99 (spot-checked: 0-25 and 90-99), hundreds `ನೂರು, ಇನ್ನೂರು, ಮುನ್ನೂರು, ನಾನ್ನೂರು, ಐನೂರು, ಆರುನೂರು, ಏಳುನೂರು, ಎಂಟುನೂರು, ಒಂಬೈನೂರು`, thousand `ಸಾವಿರ`,
years `{n} ನೂರ`, months `ಜನವರಿ, ಫೆಬ್ರವರಿ, ಮಾರ್ಚ್, ಏಪ್ರಿಲ್, ಮೇ, ಜೂನ್, ಜುಲೈ, ಆಗಸ್ಟ್, ಸೆಪ್ಟೆಂಬರ್, ಅಕ್ಟೋಬರ್, ನವೆಂಬರ್, ಡಿಸೆಂಬರ್`.

