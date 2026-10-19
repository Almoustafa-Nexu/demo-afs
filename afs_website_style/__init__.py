AFS_GREEN = '#6ba342'


def post_init_hook(env):
    """Zet de hoofdkleur van het thema (Thema > Kleuren, eerste kleur) op AFS-groen, voor elke website.
    Zo worden ook de onderdelen die Odoo zelf kleurt groen: de prijsschuif, het kruimelpad, de randen van knoppen.
    Je kunt die kleur daarna nog altijd in de editor aanpassen."""
    assets = env['website.assets']
    for website in env['website'].search([]):
        assets.with_context(website_id=website.id).make_scss_customization(
            '/website/static/src/scss/options/colors/user_color_palette.scss',
            {'o-color-1': AFS_GREEN},
        )
