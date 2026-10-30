# Writeup notes

Points to carry into the hackathon writeup. Keep each one short and true to the build.

## Known limitations

- Phone login runs in demo mode with no SMS verification, so a phone number works like a username. Real OTP
  delivery is the first change before any real deployment. (The login screen says so in English, Hindi and Marathi
  and asks people to use a made-up number.)
- Saved checks are kept for 365 days; guest checks are never stored, and a session's results live only in the
  server's memory for an hour.
- Scheme rules come from the sources listed in each scheme's YAML; some values are marked unverified or
  conflicting and the app shows them that way.
