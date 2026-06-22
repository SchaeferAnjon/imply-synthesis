module ripple8(input [7:0] a, b, input cin, output [7:0] s, output cout);
  assign {cout, s} = a + b + cin;
endmodule
