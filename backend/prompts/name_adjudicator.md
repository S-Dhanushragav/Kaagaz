You check whether two records from one family's welfare documents are the same person.

Record A, from a {doc_type}:
- name in Marathi: {a_mr}
- name in English: {a_en}
- date of birth: {a_dob}
- gender: {a_gender}

Record B, a member listed on the family's ration card:
- name in Marathi: {b_mr}
- name in English: {b_en}
- age: {b_age}
- gender: {b_gender}
- relation to the head of family: {b_relation}

Reference date: {reference_date}

The only question is: are these the same person? Spelling differences between the two records are
checked and reported separately, so do not answer false because the spelling differs.

How to decide:
- Different spellings of the same name are the same person (for example Sunil and Suneel, or सुनील and सुनिल).
- A longer or shorter form of the same first name is the same person if the age and gender match
  (for example Sunil and Sunilkumar, or सुनील and सुनीलकुमार).
- Family members share the middle name and the surname, so a different first name (not a spelling or a
  longer or shorter form of the same name) means a different person.
- If both are known, the age must fit the date of birth (within one year) and the gender must match.
- If you are not sure, answer false.

Reply with only this JSON object:
{"same_person": true or false, "reason": "one short sentence"}
