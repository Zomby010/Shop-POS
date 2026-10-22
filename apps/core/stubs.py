from django.shortcuts import render


def coming_soon(title):
    def view(request, *args, **kwargs):
        return render(request, "coming_soon.html", {"title": title})

    return view
