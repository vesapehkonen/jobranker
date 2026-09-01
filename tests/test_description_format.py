import unittest

from description_format import format_description


class DescriptionFormatTests(unittest.TestCase):
    def test_formats_sections_as_headings_and_lists_and_removes_portal_footer(self) -> None:
        blocks = format_description(
            "Introduction text\n"
            "Key Responsibilities\n"
            "Build reliable services.\n"
            "Review code.\n"
            "Required Experience Level:\n"
            "Four years of experience.\n"
            "&nbsp;\n"
            "Explore other jobs\n"
            "Report job\n"
            "Capturing job"
        )

        self.assertEqual(
            [
                {"type": "paragraph", "text": "Introduction text"},
                {"type": "heading", "text": "Key Responsibilities"},
                {"type": "list", "items": ["Build reliable services.", "Review code."]},
                {"type": "heading", "text": "Required Experience Level"},
                {"type": "paragraph", "text": "Four years of experience."},
            ],
            blocks,
        )

    def test_decodes_entities_but_leaves_output_escaping_to_template(self) -> None:
        self.assertEqual(
            [{"type": "paragraph", "text": "Research & Development <team>"}],
            format_description("Research &amp; Development &lt;team&gt;"),
        )


if __name__ == "__main__":
    unittest.main()
