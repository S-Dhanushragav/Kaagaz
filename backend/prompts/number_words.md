Write the words a {language_name} text-to-speech voice should say for numbers and dates, in {script} script, as people
in {language_name}-speaking parts of India say them aloud. Reply with one JSON object only, with these keys:

- "words": a list of exactly 100 strings, the cardinal numbers 0 to 99 in order (0, 1, 2, ... 99), each as one word or
  the usual spoken form.
- "hundreds": a list of exactly 9 strings: 100, 200, ... 900, as standalone numbers.
- "thousand": the word for "thousand" as used after a number ("two thousand"), one word.
- "century": how a year from 1100 to 1999 starts, as a pattern with {n} for the first two digits followed by the
  word for "hundred", for example "{n} hundred" in English ("nineteen hundred eighty-one").
- "months": the 12 month names, January to December, as commonly said in {language_name}.
- "labels": 5 short spoken option labels meaning "number one" ... "number five".
- "option": a pattern "{label}: {option}." in {language_name} punctuation (keep both placeholders).
- "instruction": one short sentence asking the listener to say "number one", "number two" and so on, using the labels.
- "retry": one short sentence: "Sorry, I did not catch that." followed by the instruction.
- "buttons": one short sentence: "Please tap your answer on the screen."
- "answer_numbers": a list of 5 lists; list k holds the words a person may say to pick option k: the ordinal
  ("first", "second", ...) in its common forms, the label, and the plain number word (except for "one" if that word
  also means "a").
- "not_sure": 5 short ways of saying "I don't know" / "not sure".
