$("#package-install-button").click(function(e) {
  $("#package-install-modal").modal('show');
  $("#package-install-modal input").focus();
});

$("#package-install-modal form").submit(function(e) {
  e.preventDefault();
  var command = "! pip install " + $("#package-to-install").val();
  jqconsole.ClearPromptText();
  jqconsole.Write(">>> " + command + '\n', 'jqconsole-old-input');
  jqconsole.SetHistory(jqconsole.GetHistory().concat([command]));
  sendCommand(command);
  return false;
});
