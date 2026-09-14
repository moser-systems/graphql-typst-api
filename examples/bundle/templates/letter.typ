// A second template, to show that one bundle serves many document types with
// their own query, transform and defaults.
#import "/lib/page.typ": letter, page-conf

#let data = json(bytes(sys.inputs.data))

#show: page-conf.with(sender: data.sender)

#show: letter.with(
  sender: data.sender,
  annotations: [#data.annotation],
  recipient: [
    #data.recipient.name \
    #data.recipient.street #data.recipient.house_number \
    #data.recipient.country\-#data.recipient.postal_code #data.recipient.city \
  ],
  subject: [#data.title],
  ref: [#data.reference],
)

#data.body
