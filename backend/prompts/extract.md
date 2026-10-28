You are reading photos of one Indian welfare document. The photos may be tilted, blurred, or unevenly lit. If there is more than one photo, they all show the same document: use them together, and read text from whichever photo shows it most clearly.

Step 1. Decide the document type (`doc_type`):
- `ration_card`: ration card (शिधापत्रिका) with a table of household members
- `identity_card`: identity card (ओळखपत्र, Aadhaar-style) with one person's name, date of birth, gender, and a 12-digit number
- `income_certificate`: income certificate (उत्पन्नाचा दाखला) stating annual income
- `caste_certificate`: caste certificate (जात प्रमाणपत्र) stating a category
- `other`: anything else. Then set `fields` to null.

Step 2. Extract the fields for that type, exactly as printed.
- Fields ending in `_mr` hold the Marathi text, copied in Devanagari exactly as printed. Do not transliterate or translate.
- Fields ending in `_en` hold the English text, copied exactly as printed.
- Copy spelling exactly as printed, even if it looks wrong or differs from another field. Do not correct names.
- Names and place names may be unusual. Copy them letter by letter, exactly as printed, even if they look like a misspelling of a more common word.
- Dates as DD/MM/YYYY. Ages and amounts as digits only. Financial year as YYYY-YY.
- `id_number`: write ONLY the last 4 digits, as `XXXX XXXX 1234`. Never write the other digits.
- `members`: one entry per printed row of the member table, in printed order.
- `card_colour` (ration card): the card colour printed on it, as `yellow`, `orange`, or `white`. Null if no colour is printed.
- If a field cannot be read with certainty, use null. Never guess, and never fill a value from another document or from what seems likely.

Return only the JSON object.
