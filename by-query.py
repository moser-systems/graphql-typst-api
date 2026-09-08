from gql import Client, gql
from gql.transport.aiohttp import AIOHTTPTransport
import jmespath
import typst
import json

with open("data/invoice.json") as f:
    data = json.load(f)

in_file = "invoice.typ"
out_file = "invoice"

# Select your transport with a defined url endpoint
transport = AIOHTTPTransport(url="http://localhost:8080/graphql")

# Create a GraphQL client using the defined transport
client = Client(transport=transport)

# Provide a GraphQL query
query = gql("""
query MyQuery {
  invoiceById(id: "10") {
    person {
      fullName
      addresses(filter: { type: { eq: INVOICE } }) {
        addressAddition
        countryCode
        houseNumber
        location
        postalCode
        streetName
      }
      language
    }
    description
    externalReference
    dueDate
    grossAmount
    invoiceDate
    invoiceNumber
    netAmount
    paymentConnection {
      iban
      bankAccountHolder {
        fullName
        addresses(filter: { type: { eq: RESIDENTIAL } }) {
          addressAddition
          countryCode
          houseNumber
          location
          postalCode
          streetName
        }
      }
    }
    title
    vatAmount
    positions {
      discount
      discountAmount
      discountType
      grossAmount
      name
      netAmount
      positionNumber
      quantity
      unitPrice
      vatAmount
      vatRate {
        rateInPercentage
      }
    }
    id
  }
}
""")

# Execute the query on the transport
result = client.execute(query)
print(result)

json_transformation = """
{
    "title": invoiceById.title,
    "description": invoiceById.description,
    "invoice_number": invoiceById.invoiceNumber,
    "external_reference": invoiceById.externalReference,
    "invoice_date": invoiceById.invoiceDate,
    "due_date": invoiceById.dueDate,
    "net_amount": invoiceById.netAmount,
    "gross_amount": invoiceById.grossAmount,
    "vat_amount": invoiceById.vatAmount,
    "positions": invoiceById.positions,
    "payment_connection": {
        "iban": invoiceById.paymentConnection.iban
    },
    "recipient": {
        "name": invoiceById.person.fullName,
        "street": invoiceById.person.addresses[0].streetName,
        "house_number": invoiceById.person.addresses[0].houseNumber,
        "postal_code": invoiceById.person.addresses[0].postalCode,
        "city": invoiceById.person.addresses[0].location,
        "country": invoiceById.person.addresses[0].countryCode
    },
    "qr": {
        "debtor_name": invoiceById.person.fullName,
        "debtor_street": invoiceById.person.addresses[0].streetName,
        "debtor_building": invoiceById.person.addresses[0].houseNumber,
        "debtor_postal_code": invoiceById.person.addresses[0].postalCode,
        "debtor_city": invoiceById.person.addresses[0].location,
        "debtor_country": invoiceById.person.addresses[0].countryCode,
        "amount": invoiceById.grossAmount,
        "additional_info": invoiceById.invoiceNumber
    }
}
"""

graphql_data = jmespath.search(json_transformation, result)
# print(graphql_data)


def merge_dicts(existing, updates):
    merged = existing.copy()

    for key, value in updates.items():
        if key in merged and isinstance(merged[key], dict) and isinstance(value, dict):
            merged[key] = merge_dicts(merged[key], value)
        else:
            merged[key] = value

    return merged


merged = merge_dicts(data, graphql_data)
print(merged)

sys_inputs = {"data": json.dumps(merged)}

typst.compile(
    input=in_file,
    output=f"{out_file}.pdf",
    sys_inputs=sys_inputs,
)
