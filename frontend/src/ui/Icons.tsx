// Small inline icons (no icon font to download). All are decorative: buttons carry their own labels.
import type { ReactNode } from 'react'

type P = { size?: number }

const svg = (size: number, body: ReactNode) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"
    strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" focusable="false">{body}</svg>
)

export const Logo = ({ size = 32 }: P) => (
  <svg width={size} height={size} viewBox="0 0 32 32" aria-hidden="true" focusable="false">
    <path d="M7 3h13l6 6v20H7z" fill="var(--surface)" stroke="var(--indigo)" strokeWidth="2" strokeLinejoin="round" />
    <path d="M20 3v6h6" fill="var(--saffron-tint)" stroke="var(--saffron)" strokeWidth="2" strokeLinejoin="round" />
    <path d="M11 15h11M11 19h11M11 23h7" stroke="var(--indigo)" strokeWidth="2" strokeLinecap="round" />
  </svg>
)
export const Mic = ({ size = 22 }: P) => svg(size, <><rect x="9" y="3" width="6" height="11" rx="3" /><path d="M5 11a7 7 0 0 0 14 0M12 18v3" /></>)
export const Camera = ({ size = 22 }: P) => svg(size, <><path d="M4 8h3l2-3h6l2 3h3v11H4z" /><circle cx="12" cy="13" r="3.5" /></>)
export const Send = ({ size = 22 }: P) => svg(size, <path d="M4 12l16-8-6 16-3-7z" />)
export const Menu = ({ size = 24 }: P) => svg(size, <path d="M4 7h16M4 12h16M4 17h16" />)
export const Close = ({ size = 22 }: P) => svg(size, <path d="M6 6l12 12M18 6L6 18" />)
export const Play = ({ size = 18 }: P) => svg(size, <path d="M7 5l12 7-12 7z" fill="currentColor" />)
export const Stop = ({ size = 18 }: P) => svg(size, <rect x="6" y="6" width="12" height="12" rx="1.5" fill="currentColor" />)
export const Plus = ({ size = 20 }: P) => svg(size, <path d="M12 5v14M5 12h14" />)
export const Globe = ({ size = 20 }: P) => svg(size, <><circle cx="12" cy="12" r="9" /><path d="M3 12h18M12 3c3 3 3 15 0 18M12 3c-3 3-3 15 0 18" /></>)
export const Chevron = ({ size = 18 }: P) => svg(size, <path d="M6 9l6 6 6-6" />)
export const Family = ({ size = 20 }: P) => svg(size, <><circle cx="8" cy="7" r="3" /><circle cx="17" cy="9" r="2.5" /><path d="M2 20c0-4 3-6 6-6s6 2 6 6M14 20c0-3 1.5-5 3-5s4 1.5 4 5" /></>)
export const Office = ({ size = 20 }: P) => svg(size, <><path d="M3 21h18M5 21V10l7-5 7 5v11" /><path d="M9 21v-6h6v6" /></>)
export const ThumbUp = ({ size = 20 }: P) => svg(size, <path d="M7 10v10H4V10zM7 10l4-7c1.5 0 2.5 1 2.5 2.5V9h5a2 2 0 0 1 2 2.3l-1.2 7A2 2 0 0 1 17.3 20H7" />)
export const ThumbDown = ({ size = 20 }: P) => svg(size, <path d="M7 14V4H4v10zM7 14l4 7c1.5 0 2.5-1 2.5-2.5V15h5a2 2 0 0 0 2-2.3l-1.2-7A2 2 0 0 0 17.3 4H7" />)
export const Download = ({ size = 18 }: P) => svg(size, <path d="M12 4v11M7 10l5 5 5-5M5 20h14" />)
export const DocIcon = ({ size = 44 }: P) => svg(size, <><path d="M6 3h9l4 4v14H6z" /><path d="M15 3v4h4M9 12h7M9 16h7" /></>)
export const Person = ({ size = 20 }: P) => svg(size, <><circle cx="12" cy="8" r="4" /><path d="M4 21c0-4.5 3.5-7 8-7s8 2.5 8 7" /></>)
export const Link = ({ size = 14 }: P) => svg(size, <path d="M14 4h6v6M20 4l-9 9M18 14v6H4V6h6" />)

// Problem types: one shape each, so they read without colour too.
export const IssueIcon = ({ type, size = 20 }: { type: string; size?: number }) => {
  switch (type) {
    case 'name_mismatch': return svg(size, <><path d="M4 19h4l10-10-4-4L4 15z" /><path d="M13 6l4 4" /></>)
    case 'dob_mismatch': return svg(size, <><rect x="4" y="5" width="16" height="15" rx="2" /><path d="M4 10h16M9 3v4M15 3v4" /></>)
    case 'not_on_ration_card': return svg(size, <><circle cx="10" cy="8" r="3.5" /><path d="M3 20c0-4 3-6 7-6M16 15l5 5M21 15l-5 5" /></>)
    case 'missing_document': return svg(size, <><path d="M6 3h9l4 4v14H6z" strokeDasharray="3 2" /><path d="M12 11v4M12 18v.5" /></>)
    case 'expired': return svg(size, <><circle cx="12" cy="13" r="8" /><path d="M12 9v4l3 2M9 2h6" /></>)
    case 'unreadable': return svg(size, <><path d="M3 12s3.5-6 9-6 9 6 9 6-3.5 6-9 6-9-6-9-6z" /><path d="M4 4l16 16" /></>)
    case 'waiting': return svg(size, <><path d="M4 8h3l2-3h6l2 3h3v11H4z" /><path d="M12 10v3l2 1" /></>)
    default: return svg(size, <><circle cx="12" cy="12" r="9" /><path d="M12 7v6M12 16.5v.5" /></>)
  }
}
