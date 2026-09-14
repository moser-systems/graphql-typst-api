#import "/lib/page.typ": add-zeros, letter, page-conf, parse-date, resolve-key-opt
#import "@preview/payqr-swiss:0.4.1": swiss-qr-bill
#import "@preview/datify:1.0.1": custom-date-format

// Everything below reads from a single JSON document that graphql-typst-api assembles
// from the bundle defaults and the transformed GraphQL response.
#let data = json(bytes(sys.inputs.data))

#show: page-conf.with(sender: data.sender)

#let qr-invoice = swiss-qr-bill(
  account: data.payment_connection.iban,
  creditor-name: data.qr.creditor_name,
  creditor-street: data.qr.creditor_street,
  creditor-building: data.qr.creditor_building,
  creditor-postal-code: data.qr.creditor_postal_code,
  creditor-city: data.qr.creditor_city,
  creditor-country: data.qr.creditor_country,
  amount: data.qr.amount,
  currency: data.qr.currency,
  debtor-name: data.qr.debtor_name,
  debtor-street: data.qr.debtor_street,
  debtor-building: data.qr.debtor_building,
  debtor-postal-code: data.qr.debtor_postal_code,
  debtor-city: data.qr.debtor_city,
  debtor-country: data.qr.debtor_country,
  reference-type: data.qr.reference_type, // QRR, SCOR or NON
  reference: data.qr.reference,
  additional-info: data.qr.additional_info,
  font: "Liberation Sans",
  standalone: true,
)

#show: letter.with(
  sender: data.sender,
  annotations: [#data.annotation],
  recipient: [
    #data.recipient.name \
    #data.recipient.street #data.recipient.house_number \
    #data.recipient.country\-#data.recipient.postal_code #data.recipient.city \
  ],
  subject: [#data.title],
  description: [#data.description],
  ref: [#data.invoice_number],
  ext-ref: data.external_reference,
  qr-invoice: qr-invoice,
  attachments: [
    - QR-Rechnung
  ],
)

#table(
  columns: (auto, 110mm, auto, 30mm),
  align: (left, left, auto, right),
  stroke: none,
  gutter: 0.5em,
  inset: 4pt,
  table.header(
    [*\#*], [*Beschreibung*], [*MwSt.*], [*Betrag CHF*],
    table.hline(stroke: 0.5pt),
  ),
  ..data.positions.map(p => (
    [#p.positionNumber],
    [#p.name],
    [#add-zeros(p.vatAmount) \(#resolve-key-opt(p.vatRate, "rateInPercentage", 0)%\)],
    [#add-zeros(p.grossAmount)],
    table.hline(stroke: none),
  )).flatten(),
  v(1em), [], [], [],
  table.hline(stroke: 1pt),
  [=], [*Total*], [*#add-zeros(data.vat_amount)*], [*#add-zeros(data.gross_amount)*],
  table.hline(stroke: 2pt),
)

#let payment-until-date = custom-date-format(
  parse-date(data.due_date),
  pattern: "full",
  lang: "de",
)
\
Bitte bezahlen Sie den Betrag ohne Abzug vor dem *#payment-until-date* auf das folgende
Konto gemäss beigelegter QR-Rechnung.
