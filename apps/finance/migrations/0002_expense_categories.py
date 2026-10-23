"""Expense categories become a list the owner can add to, keeping existing expenses' categories."""

import django.db.models.deletion
from django.db import migrations, models

DEFAULTS = [
    ("rent", "Rent"), ("electricity", "Electricity"), ("water", "Water"), ("transport", "Transport"),
    ("wages", "Wages"), ("packaging", "Packaging and bags"), ("licences", "Licences and permits"), ("other", "Other"),
]


def copy_categories(apps, schema_editor):
    ExpenseCategory = apps.get_model("finance", "ExpenseCategory")
    Expense = apps.get_model("finance", "Expense")
    by_code = {}
    for order, (code, name) in enumerate(DEFAULTS):
        by_code[code] = ExpenseCategory.objects.create(name=name, order=order)
    for expense in Expense.objects.all():
        expense.category_ref = by_code.get(expense.category, by_code["other"])
        expense.save(update_fields=["category_ref"])


def copy_back(apps, schema_editor):
    Expense = apps.get_model("finance", "Expense")
    codes = {name: code for code, name in DEFAULTS}
    for expense in Expense.objects.select_related("category_ref"):
        expense.category = codes.get(expense.category_ref.name, "other")
        expense.save(update_fields=["category"])


class Migration(migrations.Migration):
    dependencies = [("finance", "0001_initial")]

    operations = [
        migrations.CreateModel(
            name="ExpenseCategory",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.CharField(max_length=60, unique=True)),
                ("order", models.PositiveIntegerField(default=0)),
            ],
            options={"ordering": ["order", "name"], "verbose_name_plural": "expense categories"},
        ),
        migrations.AddField(
            model_name="expense",
            name="category_ref",
            field=models.ForeignKey(null=True, on_delete=django.db.models.deletion.PROTECT, to="finance.expensecategory"),
        ),
        migrations.RunPython(copy_categories, copy_back),
        migrations.RemoveField(model_name="expense", name="category"),
        migrations.RenameField(model_name="expense", old_name="category_ref", new_name="category"),
        migrations.AlterField(
            model_name="expense",
            name="category",
            field=models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="expenses",
                                    to="finance.expensecategory"),
        ),
    ]
