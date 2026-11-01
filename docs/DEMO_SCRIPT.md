# Demo video script

Target length: **[PLACEHOLDER: target length from the rules]** (call it T). Each beat's time is given as a share of T.
Button names are the English UI labels; in Marathi, tap the same button in the same place.

Be honest on camera: a live read of paper can differ from the sample family's results (a smudged or tilted page can
go on the clearer-photo list, or a name can be misread). If it does, show what happened; don't cut around it unless
you also use the backup take (see below).

## Before recording

- [ ] **Deploy with a warm container** for the recording day: `KAAGAZ_KEEP_WARM=1 KAAGAZ_FRONTEND_ORIGIN=<site> modal deploy deploy/modal_app.py`.
- [ ] **5 minutes before**: `python scripts/warmup.py <backend URL> --language mr kn`. This should end with "plan
      after ~15 s". It also runs the sample close-up, so that path is cached too.
- [ ] **Freeze check passes**: `python scripts/freeze_check.py --api <backend URL> --site <site URL>`, with 0 failed.
      It also confirms the "Powered by Netlify" badge is off and nothing loads from a third-party domain.
- [ ] **Logged out** in the phone's browser (account menu → "Log out"), so the app opens as a guest, as a new family
      would see it.
- [ ] **Printed SPECIMEN documents only**, never real ones. Use the printed EV012 set (`synthetic/eval_households/EV012/*.png`)
      or the HH009 set. Check that the SPECIMEN watermark is visible on every page.
- [ ] Phone: screen recorder on (with mic for narration, or narrate later), Do Not Disturb, full brightness, browser
      zoom 100%, battery above 50%.
- [ ] A table with plain cloth, good even light, no glare on laminated cards.
- [ ] A quiet room for the voice question.
- [ ] **Backup take**: record the full flow once with "Try with a sample family" (EV012's photos through the real
      pipeline). Use it if the live paper read misbehaves, and say in the voice-over that it is the sample family.
- [ ] Optional: `?sample=video` at the end of the site URL runs the HH009 sweep video as the sample instead (testing only).

## Beats

### 0. Cold open (3 seconds, before beat 1)

- **Shots:** the phone in hand, screen filling the frame: the schemes matrix of a finished Marathi check.
- **On screen:** "Listen to all" already playing; the phone speaks the first plan sentence in Marathi over the matrix.
- **Narration:** none (the phone's voice only). Record it from the warm sample check, then cut to beat 1.

### 1. A family's problem (~10% of T)

- **Shots:** close-up of a table with a ration card, Aadhaar cards and certificates; a hand turning a page.
- **On screen:** none (b-roll), then the app's welcome screen on the phone.
- **Narration:** "Families lose welfare benefits over small paperwork problems: a name spelled two ways, a date of
  birth that doesn't match, a certificate that's too old. They find out weeks later, after a wasted trip. Kaagaz
  checks the papers before they apply, and says what to fix, in their language."

### 2. Filming real paper on a phone, in Marathi (~15% of T)

- **Shots:** over-the-shoulder phone view; screen recording side by side.
- **On screen:** choose मराठी → "Record your documents" → read the "Before you record" guidance → "Start recording" →
  move slowly over every printed SPECIMEN page (under 45 s) → "Stop". (Or "Add photos" and take one photo per page.)
- **Narration:** "The papers are printed specimens, never real documents. We pick Marathi and sweep the camera
  slowly over everything on the table."

### 3. Documents found, Aadhaar numbers blurred (~10% of T)

- **Shots:** screen recording of the progress list and thumbnails filling in.
- **On screen:** "Finding documents" → thumbnails appear one by one, labelled with the owner's name; zoom in on an
  Aadhaar thumbnail with the number blurred.
- **Narration:** "Meta's SAM 3.1 finds each document and Muse Spark reads it. On Aadhaar cards the number is blurred
  before anything is shown, and it's masked before anything is stored."

### 4. The close-up loop (~10% of T)

- **Shots:** screen recording.
- **On screen:** the card "Some documents need a clearer photo" → "Take a photo" of the listed document (or, in the
  backup take, "Use sample close-up" on the father's caste certificate) → "Reading the photo…" → the plan updates.
- **If the live paper take has no unclear document:** use this beat from the sample backup take ("Use sample
  close-up" on the father's caste certificate), and say so in the voice-over: "Here, from the sample family: ..."
- **Narration:** "One certificate was too blurry to trust. Kaagaz doesn't guess: it asks for a clearer photo, reads
  it, and checks everything again in a few seconds."

### 5. The matrix and the plan, read aloud (~15% of T)

- **Shots:** screen recording, with phone audio audible.
- **On screen:** if a question appears (e.g. which date of birth is right), tap the right answer → scroll the schemes
  matrix (members × 5 schemes: eligible, fix first, check at the office, not eligible) → tap one cell to show its
  reasons and source → "Listen to all".
- **Narration (over the first few seconds of speech):** "Each person against five schemes. Eligibility is decided by
  plain rules from official sources, never by the AI. The plan comes from a fixed list of real procedures, read
  aloud in Marathi."

### 6. Ask Kaagaz by voice about Lata's date of birth (~15% of T)

- **Shots:** screen recording; face or hand near the phone while speaking.
- **On screen:** tap the mic ("Ask by voice") → ask in Marathi the app's own suggested question for a date-of-birth
  mismatch (`ask.suggestions.dob_mismatch`: "{member}: जन्मतारखेबद्दल काय करायचे?"): "लता दत्तात्रय कदम:
  जन्मतारखेबद्दल काय करायचे?" (the same words appear as a suggested-question chip, so the viewer can compare) → tap to
  stop → "Check the words, then send." → "Send" → the answer plays by itself; show its sources.
- **Narration:** "Families can ask in their own words. Muse Voice Transcribe writes the question down so they can
  check it, and Muse Spark Open answers. Code checks every fact in the answer before it's shown."

### 7. Switching to Kannada (~10% of T)

- **Shots:** screen recording.
- **On screen:** "Language" → ಕನ್ನಡ. A check keeps its language, so start a new check: "Try with a sample family"
  (fast, since it's cached) → show the Kannada matrix and the machine-translated label → "Listen" on one step.
- **Narration:** "Six languages: Marathi, Hindi, English, Tamil, Telugu and Kannada. Names stay as they are written on
  the documents, and the app says clearly which languages are machine-translated."

### 8. How the safety checks work (~15% of T)

- **Shots:** simple title cards or a screen capture of the diagram in `docs/WRITEUP.md`; end on the app.
- **On screen:** none, or the "How Kaagaz works" card in the welcome.
- **Narration:** "The AI reads and explains. It doesn't decide. Rules decide eligibility. Fixes come only from
  verified procedures, and when there's no match, Kaagaz says to ask at the office. Ask answers are fact-checked by
  code; when the check fails, Kaagaz says it isn't sure. ID numbers are blurred, uploads are deleted after reading,
  and a guest's check is never stored. Everything you saw used specimen documents."

## After recording

- [ ] Check that no real document or real phone number appears in any frame.
- [ ] Captions in English for the Marathi and Kannada audio.
- [ ] Add the video URL to `docs/WRITEUP.md` ([PLACEHOLDER: video URL]).
