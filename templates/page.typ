
#let page-conf(
  skip_footer: false,
  folding-marks: true,
  hole-mark: true,
  body
) = {
  set page(
    paper: "a4",
    margin: (
      top: 2cm,
      bottom: 2.5cm,
      left: 1.5cm,
      right: 1.5cm
    ),
    background: {
      if hole-mark {
        // hole mark
        place(left + top, dx: 5mm, dy: 148.5mm, line(
          length: 4mm,
          stroke: 0.25pt + black
        ))
      }
    },
    header-ascent: 0pt,
    header: context {
      show: pad.with(top: 20pt)
      image("../assets/moser-immo-ag-f.png")
    },
    footer-descent: 0%,
    footer: context {
      if (not skip_footer) {
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
              *Moser Maschinen und Immobilien AG* \
              Bahnhofstrasse 276, Postfach 248, CH-4563 Gerlafingen, Switzerland \
              +41 32 674 55 77 | info\@moser-immo.ch | www.moser-immo.ch | CHE-113.701.199\
            ]
          },
          align(right)[Seite #current-page von #page-count],
        )
      }
    },
  )
  set par(justify: true)
  set text(
    font: "Liberation Sans",
    size: 10pt,
  )
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
    // https://typst.app/docs/reference/layout/page/#parameters-margin
    return calc.min(page.width, page.height) * 2.5 / 21
  }
  return m
}

#let top-margin() = get-margin("top")
#let left-margin() = get-margin("left", "inside")

#let date = datetime.today()

#let left-box-right = 105mm

#let content-box(x, y, width, height, framed: false, content) = context place(
  top + left,
  dx: x - left-margin(),
  dy: y - top-margin(),
  box(width: width, height: height, stroke: if framed { 0.25pt }, content)
)

#let relative-box(x, width, height, framed: false, content) = context place(
  left,
  dx: x - left-margin(),
  box(width: width, height: height, stroke: if framed { 0.25pt }, content)
)

/////// LETTER
#let letter(
  recipient: none,
  annotations: none,
  subject: none,
  description: none,
  ref: none,
  ext_ref: none,
  attachments: none,
  author-name: none,
  author-email: none,
  author-phone: none,
  qr-invoice: none,
  body
) = {

  content-box(15mm, 91mm, 60mm, 15mm, framed: false)[
    #table(
      columns: (auto, auto),
      align: (right, left),
      stroke: none,
      gutter: 5pt,
      inset: 0pt,
      [*Referenz:*], [#ref],
    )
  ]

  content-box(left-box-right, 40mm, 90mm, 50mm, framed: false)[
      #text(size: 8pt, "Moser Maschinen und Immobilien AG, PF 248, CH-4563 Gerlafingen") \
      \
      #text(size: 8pt, upper[*#annotations*]) \
      #recipient \
  ]

  content-box(left-box-right, 90mm, 90mm, 5mm, framed: false)[
      Gerlafingen, #date.display("[day].[month].[year]")
  ]

  v(8.5cm)
  text(size: 16pt,[
    *#subject* \
  ])
  text(size: 10pt,[
    *Betrifft:*\
    #description\
  ])
  if (ext_ref != none) {
    text(size: 10pt,[
      *Ihre Referenz:* #ext_ref\
    ])
  }
  v(1em)

  body
  v(2em)

  relative-box(left-box-right, 80mm, 20mm)[
    Freundliche Grüsse \
    #v(2em)
    Moser Maschinen und Immobilien AG \
    //#author-name
  ]

  if (attachments != none) {
    v(1fr)
    text(size: 10pt,[
      *Beilagen:*
    ])
    attachments
  }
  v(1cm)
    if (qr-invoice != none) {
    v(1em)
    qr-invoice
  }
}

#let parse-date = (date-str) => {
  let parts = date-str.split("-")
  if parts.len() != 3 {
    panic(
      "Invalid date string: " + date-str + "\n" +
      "Expected format: YYYY-MM-DD"
    )
  }
  datetime(
    year: int(parts.at(0)),
    month: int(parts.at(1)),
    day: int(parts.at(2)),
  )
}

#let add-zeros = (num) => {
    // Can't use trunc and fract due to rounding errors
    let frags = str(num).split(".")
    let (intp, decp) = if frags.len() == 2 { frags } else { (num, "00") }
    str(intp) + "." + (str(decp) + "00").slice(0, 2)
}

#let resolve-opt(x, default) = {
    if (x != none) {
        return x
    }
    else {
        return default
    }
}

#let resolve-key-opt(x, key, default) = {
    if (x != none) {
        if (key != none) {
            return x.at(key)
        }
        else {
            return x
        }
    } else {
        return default
    }
}
