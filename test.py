import typst
import json

with open("data/data.json") as f:
    data = json.load(f)

in_file = "letter_py.typ"
out_file = "letter-py"
sys_inputs = {"data": json.dumps(data)}


typst.compile(
    input=in_file,
    output=f"{out_file}.pdf",
    sys_inputs=sys_inputs,
)
