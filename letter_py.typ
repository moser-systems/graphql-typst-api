#import "templates/page.typ": page-conf, letter

#let data = json(bytes(sys.inputs.data))

#show: page-conf.with(skip_footer: false)

#show: letter.with(
  annotations: [#data.annotation],
  recipient: [
    #data.recipient.name\
    #data.recipient.street\
    #data.recipient.postal_code #data.recipient.city\
    #data.recipient.country
  ],
  subject: data.subject,
  ref: data.ref,
  author: data.author,
  attachments: [
      - Photos,
      - Copy of the invoice
  ]
)

Sehr geehrte Damen und Herren

Die von mir bei den Werbekosten geltend gemachte Abschreibung für den im
vergangenen Jahr a  ngeschafften Fotokopierer wurde von Ihnen nicht berücksichtigt.
Der Fotokopierer steht in meinem Büro und wird von mir ausschließlich zu beruflichen
Zwecken verwendet.

Ich lege deshalb Einspruch gegen den oben genannten Einkommensteuerbescheid ein
und bitte Sie, die Abschreibung anzuerkennen.

Anbei erhalten Sie eine Kopie der Rechnung des Gerätes.
