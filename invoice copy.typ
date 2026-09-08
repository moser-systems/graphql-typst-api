#import "templates/page.typ": page-conf, letter, parse-date, add-zeros, resolve-opt
#import "@preview/payqr-swiss:0.4.1": swiss-qr-bill
#import "@preview/datify:1.0.1": custom-date-format

#show: page-conf.with(skip_footer: false)

#let data = json(bytes(sys.inputs.data))

#let qr-invoice = swiss-qr-bill(
  account: resolve-opt(data.rentalContract.paymentConnection.iban, data.defaultPaymentConnection.iban),
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
  reference-type: "QRR",  // QRR, SCOR, or NON
  reference: data.qr.reference,
  additional-info: data.qr.additional_info,
  font: "Liberation Sans",
  standalone: true,
)

#show: letter.with(
  annotations: [#data.annotation],
  recipient: [
    #data.recipient.name\
    #data.recipient.street #data.recipient.house_number\
    #data.recipient.country\-#data.recipient.postal_code #data.recipient.city\
  ],
  subject: [#data.subject #data.rentalContract.ref_id],
  ref: [#data.rentalContract.description, #data.building.full_address],
  ext_ref: [test #data.rentalContract.ext_ref],
  author-name: data.author.name,
  author-email: data.author.email,
  author-phone: data.author.phone,
  qr-invoice: qr-invoice,
  attachments: [
      - QR-Rechnung
  ]
)

#table(
  columns: (
    140mm,
    auto,
    30mm,
  ),
  align: (left, auto, right),
  stroke: none,
  gutter: 0.5em,
  inset: 4pt,
  table.header(
    [*Beschreibung*], [], [*Betrag*],
    table.hline(stroke: 0.5pt),
  ),
  [#data.rentalAccountEntry.description], [CHF], [#add-zeros(data.rentalAccountEntry.amount)],
  table.hline(stroke: none),
  [Total], [CHF], [#add-zeros(data.rentalAccountEntry.amount)],
  table.hline(stroke: 2pt),
)

#let payment-until-date = custom-date-format(parse-date(data.rentalAccountEntry.valid_from), pattern: "full", lang: "de")
\
Bitte bezahlen Sie den Betrag ohne Abzug bis spätestens *#payment-until-date* auf das folgende Konto gemäss beigelegter QR-Rechnung.
\
\
