import { brandImage } from "../brandImages";

/**
 * Site footer.
 *
 * Opening hours and contact details are the restaurant's own - they are
 * written here rather than fetched, because the backend has no settings
 * endpoint that is public, and inventing them from a defaults endpoint
 * would risk showing hours the restaurant never set. Change these four
 * constants when the details change.
 */

const HOURS = [
  { day: "Monday – Thursday", time: "12:00 – 22:30" },
  { day: "Friday – Saturday", time: "12:00 – 23:30" },
  { day: "Sunday", time: "12:00 – 23:00" },
];

const CONTACT = {
  address: "Paradise Restaurant, Banjara Hills Road No. 12, Hyderabad 500034",
  phone: "+91 40 4000 1234",
  email: "reservations@paradiserestaurant.example",
};

const SOCIALS = [
  {
    label: "Instagram",
    href: "https://instagram.com/",
    path: "M12 7.6a4.4 4.4 0 1 0 0 8.8 4.4 4.4 0 0 0 0-8.8Zm0 7.2a2.8 2.8 0 1 1 0-5.6 2.8 2.8 0 0 1 0 5.6ZM17.8 6.2a1 1 0 1 1-2 0 1 1 0 0 1 2 0ZM7.6 3.5h8.8A4.1 4.1 0 0 1 20.5 7.6v8.8a4.1 4.1 0 0 1-4.1 4.1H7.6a4.1 4.1 0 0 1-4.1-4.1V7.6a4.1 4.1 0 0 1 4.1-4.1Zm0 1.8A2.3 2.3 0 0 0 5.3 7.6v8.8a2.3 2.3 0 0 0 2.3 2.3h8.8a2.3 2.3 0 0 0 2.3-2.3V7.6a2.3 2.3 0 0 0-2.3-2.3H7.6Z",
  },
  {
    label: "Facebook",
    href: "https://facebook.com/",
    path: "M13.5 21v-8h2.7l.4-3.1h-3.1V7.9c0-.9.3-1.5 1.6-1.5h1.6V3.6A22 22 0 0 0 14.3 3.5c-2.4 0-4 1.5-4 4.2v2.2H7.6V13h2.7v8h3.2Z",
  },
  {
    label: "X",
    href: "https://x.com/",
    path: "M17.6 3h2.9l-6.4 7.3L21.8 21h-5.9l-4.6-6-5.3 6H3.1l6.9-7.9L3 3h6l4.2 5.5L17.6 3Zm-1 16.2h1.6L7.5 4.7H5.8l10.8 14.5Z",
  },
];

export function Footer() {
  return (
    <footer className="site-footer" id="contact">
      <div
        className="site-footer-wash"
        style={{ backgroundImage: `url(${brandImage("restaurant-interior")})` }}
        aria-hidden="true"
      />

      <div className="shell site-footer-inner">
        <div className="site-footer-brand">
          <span className="site-brand-mark" aria-hidden="true">
            <svg viewBox="0 0 32 32" width="30" height="30" fill="none">
              <path
                d="M16 5c-4.6 0-8.3 3.5-8.3 7.9v1.2h16.6v-1.2C24.3 8.5 20.6 5 16 5Z"
                stroke="var(--gold-primary)"
                strokeWidth="1.6"
              />

              <path
                d="M5.4 16.6h21.2M7.7 19.6h16.6M9.6 22.6h12.8"
                stroke="var(--gold-primary)"
                strokeWidth="1.6"
                strokeLinecap="round"
              />
            </svg>
          </span>

          <h3 className="gold-text">Paradise Restaurant</h3>

          <p>
            Good food, great mood. A dining room built around slow service,
            warm light and food worth travelling for.
          </p>

          <ul className="site-socials">
            {SOCIALS.map((social) => (
              <li key={social.label}>
                <a
                  href={social.href}
                  target="_blank"
                  rel="noreferrer noopener"
                  aria-label={social.label}
                >
                  <svg viewBox="0 0 24 24" width="17" height="17" fill="currentColor">
                    <path d={social.path} />
                  </svg>
                </a>
              </li>
            ))}
          </ul>
        </div>

        <nav className="site-footer-col" aria-label="Quick links">
          <h4>Quick Links</h4>

          <ul>
            <li>
              <a href="#top">Home</a>
            </li>
            <li>
              <a href="#menu">Menu</a>
            </li>
            <li>
              <a href="#recommendations">AI Picks For You</a>
            </li>
            <li>
              <a href="#reserve">Reservations</a>
            </li>
            <li>
              <a href="#about">About</a>
            </li>
            <li>
              <a href="#contact">Contact</a>
            </li>
          </ul>
        </nav>

        <div className="site-footer-col">
          <h4>Opening Hours</h4>

          <ul className="site-hours">
            {HOURS.map((row) => (
              <li key={row.day}>
                <span>{row.day}</span>
                <strong>{row.time}</strong>
              </li>
            ))}
          </ul>
        </div>

        <div className="site-footer-col" id="contact-details">
          <h4>Contact</h4>

          <ul className="site-contact">
            <li>{CONTACT.address}</li>
            <li>
              <a href={`tel:${CONTACT.phone.replace(/\s/g, "")}`}>
                {CONTACT.phone}
              </a>
            </li>
            <li>
              <a href={`mailto:${CONTACT.email}`}>{CONTACT.email}</a>
            </li>
          </ul>
        </div>
      </div>

      <div className="site-footer-base">
        <div className="shell">
          <p>© Paradise Restaurant. All Rights Reserved.</p>
        </div>
      </div>
    </footer>
  );
}

export default Footer;
