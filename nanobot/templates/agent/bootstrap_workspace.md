{% for item in bootstrap_files %}
## {{ item.filename }}

{{ item.content }}{% if not loop.last %}

{% endif %}
{% endfor %}
