pdf:
	typst compile letter.typ dist/letter.pdf
	typst compile invoice.typ dist/invoice.pdf

pdfs-2026:
	mkdir -p pdfs
	for file in data/2026/*.yaml; do \
		base=$$(basename "$$file" .yaml); \
		typst compile invoice.typ "pdfs/$$base.pdf" --input data_file="$$file"; \
	done

watch-pdf:
	while inotifywait -e close_write letter.typ; do typst compile letter.typ dist/letter.pdf; done

update:
	pip install --upgrade pip pip-tools
	pip-compile -U --no-header --no-annotate --strip-extras --resolver=backtracking
	pip-sync
