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
  defaultPaymentConnection {
    bic
    iban
  }
  rentalAccountEntryById(id: "7533") {
    amount
    description
    rentalContract {
      tenants {
        person {
          fullName
          addresses {
            countryCode
            houseNumber
            location
            postalCode
            streetName
            types
          }
        }
      }
      description
      dueOnDay
      extensionInMonths
      expirationDate
      payable
      noticePeriodInMonths
      validFrom
      validUntil
      additionalCharge
      additionalChargeIsFlatRate
      building {
        fullAddress
      }
      paymentConnection {
        iban
        name
      }
      paymentPeriod
      rent
      refId
      externalReference
    }
    validFrom
    validUntil
  }
}
""")

# Execute the query on the transport
result = client.execute(query)
print(result)

json_transformation = """
{
    "building": {
        "full_address": rentalAccountEntryById.rentalContract.building.fullAddress
    },
    "defaultPaymentConnection": {
        "iban": defaultPaymentConnection.iban
    },
    "rentalAccountEntry": {
        "description": rentalAccountEntryById.description,
        "amount": rentalAccountEntryById.amount,
        "valid_from": rentalAccountEntryById.validFrom,
        "valid_until": rentalAccountEntryById.validUntil
    },
    "rentalContract": {
        "description": rentalAccountEntryById.rentalContract.description,
        "paymentConnection": {
            "iban": rentalAccountEntryById.rentalContract.paymentConnection.iban
        },
        "ref_id": rentalAccountEntryById.rentalContract.refId,
        "ext_ref": rentalAccountEntryById.rentalContract.externalReference
    },
    "recipient": {
        "name": rentalAccountEntryById.rentalContract.tenants[0].person.fullName,
        "street": rentalAccountEntryById.rentalContract.tenants[0].person.addresses[0].streetName,
        "house_number": rentalAccountEntryById.rentalContract.tenants[0].person.addresses[0].houseNumber,
        "postal_code": rentalAccountEntryById.rentalContract.tenants[0].person.addresses[0].postalCode,
        "city": rentalAccountEntryById.rentalContract.tenants[0].person.addresses[0].location,
        "country": rentalAccountEntryById.rentalContract.tenants[0].person.addresses[0].countryCode
    },
    "qr": {
        "debtor_name": rentalAccountEntryById.rentalContract.tenants[0].person.fullName,
        "debtor_street": rentalAccountEntryById.rentalContract.tenants[0].person.addresses[0].streetName,
        "debtor_building": rentalAccountEntryById.rentalContract.tenants[0].person.addresses[0].houseNumber,
        "debtor_postal_code": rentalAccountEntryById.rentalContract.tenants[0].person.addresses[0].postalCode,
        "debtor_city": rentalAccountEntryById.rentalContract.tenants[0].person.addresses[0].location,
        "debtor_country": rentalAccountEntryById.rentalContract.tenants[0].person.addresses[0].countryCode,
        "amount": rentalAccountEntryById.amount,
        "additional_info": rentalAccountEntryById.rentalContract.refId
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
