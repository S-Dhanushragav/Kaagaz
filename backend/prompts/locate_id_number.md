This is a photo of an Indian identity card (Aadhaar-style). Find every place where the identity number is printed:
the 12-digit identity (Aadhaar) number, and a 16-digit Virtual ID (VID) if there is one.

For each one, give a bounding box that covers all of its digits, in normalized coordinates:
- x0, y0: the top-left corner; x1, y1: the bottom-right corner
- as fractions of the image width (x) and height (y), from 0 to 1

Do not write the digits themselves. If no identity number is visible, reply with an empty list.

Reply with only this JSON object:
{"boxes": [{"x0": 0.0, "y0": 0.0, "x1": 0.0, "y1": 0.0}]}
