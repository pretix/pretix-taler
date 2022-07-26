$(function () {
    function check () {
        $.getJSON(
            location.href + '?ajax=1',
        ).done(function (json) {
            if (json.refresh) {
                location.reload()
            } else {
                window.setTimeout(check, 10000);
            }
        }).fail(function (jqxhr, textStatus, error) {
            window.setTimeout(check, 20000);
        })
    }
    window.setTimeout(check, 10000);
})