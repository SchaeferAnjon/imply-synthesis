module comp2(input [1:0] a, b, output eq, lt);
  assign eq = (a == b);
  assign lt = (a < b);
endmodule
