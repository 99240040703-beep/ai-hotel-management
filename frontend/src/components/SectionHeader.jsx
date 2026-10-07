/**
 * A section heading with the site's gold eyebrow treatment.
 *
 * Used by every public section so the rhythm - eyebrow, title, supporting
 * line - stays identical rather than being re-invented per section.
 */
export function SectionHeader({
  eyebrow,
  title,
  subtitle,
  align = "center",
  id,
  children,
}) {
  return (
    <header className={`section-header section-header-${align}`} id={id}>
      {eyebrow && <span className="eyebrow">{eyebrow}</span>}

      {title && (
        <h2>
          {title}
          {/* The rule sits under the title rather than beside it, which
              holds up at every width without a second breakpoint. */}
          <span className="section-header-rule" aria-hidden="true" />
        </h2>
      )}

      {subtitle && <p className="section-header-sub">{subtitle}</p>}

      {children}
    </header>
  );
}

export default SectionHeader;
