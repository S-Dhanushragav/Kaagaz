Each item has an English source text ("source") and the English back-translation ("back") of its {language_name}
translation. Decide whether the translation keeps the meaning of the source for a user of a welfare-documents app.

Mark "same": false only for a real difference in meaning: a fact, number, condition, negation, warning, person or
action that is added, dropped or changed, or a sentence that would mislead or confuse the user. Differences of wording,
word order, politeness, singular/plural of a general noun, or a more literal back-translation are "same": true.

Reply with one JSON object only: for each key, {"same": true} or {"same": false, "difference": "<one short sentence>"}.

Items (JSON):
{items}
