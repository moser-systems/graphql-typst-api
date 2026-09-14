// Shared letterhead. Everything company-specific arrives through the `sender`
// dictionary, which comes from the bundle's global defaults file — so a new
// deployment changes defaults.yaml rather than this file.

#let page-conf(
  sender: (:),
  skip-footer: false,
  hole-mark: true,
  body,
) = {
  set page(
    paper: "a4",
    margin: (top: 2cm, bottom: 2.5cm, left: 1.5cm, right: 1.5cm),
    background: {
      if hole-mark {
        place(left + top, dx: 5mm, dy: 148.5mm, line(length: 4mm, stroke: 0.25pt + black))
      }
    },
    header-ascent: 0pt,
    header: context {
      show: pad.with(top: 20pt)
      grid(
        columns: (auto, 1fr),
        column-gutter: 12pt,
        align: (left + horizon, right + horizon),
        image("/assets/logo.png", width: 18mm),
        text(size: 18pt, weight: "bold", sender.at("name", default: "")),
      )
    },
    footer-descent: 0%,
    footer: context {
      if not skip-footer {
        show: pad.with(top: 12pt)
        set text(size: 8pt)
        let current-page = counter(page).get().first()
        let page-count = counter(page).final().first()
        grid(
          columns: 1fr,
          rows: (0.65em, 1fr),
          row-gutter: 12pt,
          if current-page == 1 {
            align(left)[
              *#sender.at("name", default: "")* \
              #sender.at("address", default: "") \
              #sender.at("contact", default: "")
            ]
          },
          align(right)[Seite #current-page von #page-count],
        )
      }
    },
  )
  set par(justify: true)
  set text(font: ("Liberation Sans", "DejaVu Sans"), size: 10pt)
  v(1em)
  body
}

#let get-margin(..sides) = {
  let m = if type(page.margin) == relative or page.margin == auto {
    page.margin
  } else {
    page.margin.at(sides.pos().find(s => s in page.margin))
  }
  if m == auto {
    return calc.min(page.width, page.height) * 2.5 / 21
  }
  return m
}

#let top-margin() = get-margin("top")
#let left-margin() = get-margin("left", "inside")

#let left-box-right = 105mm

#let content-box(x, y, width, height, framed: false, content) = context place(
  top + left,
  dx: x - left-margin(),
  dy: y - top-margin(),
  box(width: width, height: height, stroke: if framed { 0.25pt }, content),
)

#let relative-box(x, width, height, framed: false, content) = context place(
  left,
  dx: x - left-margin(),
  box(width: width, height: height, stroke: if framed { 0.25pt }, content),
)

#let letter(
  sender: (:),
  recipient: none,
  annotations: none,
  subject: none,
  description: none,
  ref: none,
  ext-ref: none,
  attachments: none,
  qr-invoice: none,
  date: none,
  body,
) = {
  // The letter date is passed in rather than read from the clock, so a rendered
  // PDF is reproducible.
  let letter-date = if date == none { datetime.today() } else { date }

  content-box(15mm, 91mm, 60mm, 15mm)[
    #table(
      columns: (auto, auto),
      align: (right, left),
      stroke: none,
      gutter: 5pt,
      inset: 0pt,
      [*Referenz:*], [#ref],
    )
  ]

  content-box(left-box-right, 40mm, 90mm, 50mm)[
    #text(size: 8pt, sender.at("return_line", default: "")) \
    \
    #text(size: 8pt, upper[*#annotations*]) \
    #recipient \
  ]

  content-box(left-box-right, 90mm, 90mm, 5mm)[
    #sender.at("place", default: ""), #letter-date.display("[day].[month].[year]")
  ]

  v(8.5cm)
  text(size: 16pt)[*#subject* \ ]
  if description != none {
    text(size: 10pt)[
      *Betrifft:* \
      #description \
    ]
  }
  if ext-ref != none {
    text(size: 10pt)[*Ihre Referenz:* #ext-ref \ ]
  }
  v(1em)

  body
  v(2em)

  relative-box(left-box-right, 80mm, 20mm)[
    Freundliche Grüsse \
    #v(2em)
    #sender.at("name", default: "")
  ]

  if attachments != none {
    v(1fr)
    text(size: 10pt)[*Beilagen:*]
    attachments
  }
  v(1cm)
  if qr-invoice != none {
    v(1em)
    qr-invoice
  }
}

// GraphQL hands back plain ISO dates; typst wants a datetime.
#let parse-date = (date-str) => {
  let parts = date-str.split("-")
  if parts.len() != 3 {
    panic("Invalid date string: " + date-str + "\nExpected format: YYYY-MM-DD")
  }
  datetime(year: int(parts.at(0)), month: int(parts.at(1)), day: int(parts.at(2)))
}

// String-based so amounts never pick up binary float rounding.
#let add-zeros = (num) => {
  let frags = str(num).split(".")
  let (intp, decp) = if frags.len() == 2 { frags } else { (num, "00") }
  str(intp) + "." + (str(decp) + "00").slice(0, 2)
}

#let resolve-opt(x, default) = if x != none { x } else { default }

#let resolve-key-opt(x, key, default) = {
  if x == none { return default }
  if key == none { return x }
  return x.at(key, default: default)
}
